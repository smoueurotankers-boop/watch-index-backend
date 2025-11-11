from flask import Flask, request, jsonify
import os
import base64
import requests
from datetime import datetime
import csv
import json
from io import StringIO

app = Flask(__name__)


def commit_to_github(filename: str, content: bytes, message: str = "Add submission") -> bool:
    """Commit a file to the configured GitHub repository using the contents provided.

    Args:
        filename: The filename (path relative to the repo root) to commit.
        content: Raw byte content of the file.
        message: Commit message.

    Returns:
        True if the commit succeeded, False otherwise.
    """
    token = os.getenv("GITHUB_TOKEN")
    repo_full_name = os.getenv("REPO_FULL_NAME")
    if not token or not repo_full_name:
        print("GITHUB_TOKEN or REPO_FULL_NAME environment variable not set.")
        return False

    url = f"https://api.github.com/repos/{repo_full_name}/contents/{filename}"
    encoded_content = base64.b64encode(content).decode('utf-8')
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    data = {
        "message": message,
        "content": encoded_content,
        "branch": "main",
    }
    response = requests.put(url, json=data, headers=headers)
    if response.status_code in (201, 200):
        return True
    else:
        print(f"GitHub API returned {response.status_code}: {response.text}")
        return False


def get_all_submissions_from_github():
    """Fetch all CSV files from the submissions directory in GitHub.
    
    Returns:
        List of CSV content strings, or empty list if error.
    """
    token = os.getenv("GITHUB_TOKEN")
    repo_full_name = os.getenv("REPO_FULL_NAME")
    if not token or not repo_full_name:
        print("GITHUB_TOKEN or REPO_FULL_NAME environment variable not set.")
        return []
    
    submissions = []
    url = f"https://api.github.com/repos/{repo_full_name}/contents/submissions"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            files = response.json()
            for file in files:
                if file['name'].endswith('.csv') and file['name'] != 'sample_submission.csv':
                    file_response = requests.get(file['download_url'])
                    if file_response.status_code == 200:
                        submissions.append(file_response.text)
        return submissions
    except Exception as e:
        print(f"Error fetching submissions from GitHub: {e}")
        return []


def aggregate_submissions(csv_contents):
    """Aggregate CSV submissions and calculate metrics.
    
    Args:
        csv_contents: List of CSV content strings.
    
    Returns:
        Dictionary with aggregated metrics.
    """
    totals = {"submissions": 0}
    sums = {"sleep": 0.0, "rest": 0.0}
    by_ship = {}
    by_region = {}
    
    for csv_content in csv_contents:
        try:
            reader = csv.DictReader(StringIO(csv_content))
            for row in reader:
                if not row.get('ship_type') or not row.get('region'):
                    continue
                
                totals["submissions"] += 1
                
                try:
                    sleep = float(row.get('sleep_hours', 0) or 0)
                except ValueError:
                    sleep = 0.0
                try:
                    rest = float(row.get('rest_violations', 0) or 0)
                except ValueError:
                    rest = 0.0
                
                sums["sleep"] += sleep
                sums["rest"] += rest
                
                ship = row['ship_type'].strip()
                region = row['region'].strip()
                by_ship[ship] = by_ship.get(ship, 0) + 1
                by_region[region] = by_region.get(region, 0) + 1
        except Exception as e:
            print(f"Error processing CSV: {e}")
            continue
    
    averages = {
        "sleepHours": round(sums["sleep"] / totals["submissions"], 2) if totals["submissions"] else 0,
        "restViolations": round(sums["rest"] / totals["submissions"], 2) if totals["submissions"] else 0,
    }
    
    metrics = {
        "totals": totals,
        "averages": averages,
        "byShip": by_ship,
        "byRegion": by_region,
        "updatedAt": datetime.utcnow().isoformat()
    }
    
    return metrics


def update_data_json():
    """Fetch all submissions, aggregate them, and commit the updated data.json.
    
    Returns:
        True if successful, False otherwise.
    """
    token = os.getenv("GITHUB_TOKEN")
    repo_full_name = os.getenv("REPO_FULL_NAME")
    if not token or not repo_full_name:
        print("GITHUB_TOKEN or REPO_FULL_NAME environment variable not set.")
        return False
    
    try:
        submissions = get_all_submissions_from_github()
        print(f"Found {len(submissions)} submission files")
        
        metrics = aggregate_submissions(submissions)
        print(f"Aggregated metrics: {metrics['totals']['submissions']} submissions")
        
        data_json_content = json.dumps(metrics, indent=2).encode('utf-8')
        success = commit_to_github('data/data.json', data_json_content, 'Update aggregated metrics')
        
        if success:
            print("Successfully updated data.json")
            return True
        else:
            print("Failed to commit data.json")
            return False
    except Exception as e:
        print(f"Error updating data.json: {e}")
        return False


@app.route('/upload', methods=['POST'])
def upload_file():
    """Endpoint to handle file submissions and commit them to GitHub.

    Expects a multipart/form-data POST request with a file field named
    "submission" containing a CSV file. The file will be stored in the
    `submissions/` directory of the configured repository.
    """
    if 'submission' not in request.files:
        return jsonify({'error': 'No submission file provided.'}), 400
    file = request.files['submission']
    if file.filename == '':
        return jsonify({'error': 'Empty filename.'}), 400
    try:
        content = file.read()
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        safe_filename = file.filename.replace("..", "_")
        target_path = f"submissions/{timestamp}_{safe_filename}"
        commit_message = f"Add submission {safe_filename} on {timestamp}"
        success = commit_to_github(target_path, content, commit_message)
        if success:
            update_data_json()
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'error': 'Failed to commit file to GitHub.'}), 500
    except Exception as e:
        print(f"Exception while processing upload: {e}")
        return jsonify({'error': 'Internal server error.'}), 500

# For Vercel: expose the Flask app as a WSGI callable
# Vercel looks for `app` or `application` in the module for WSGI apps.
# Here we expose it as `app` so Vercel can serve it.

# The following section allows the app to run locally with `python app.py`
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
