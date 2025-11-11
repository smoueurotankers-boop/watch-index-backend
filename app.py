from flask import Flask, request, jsonify
import os
import base64
import requests
import json
import csv
from io import StringIO
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib

app = Flask(__name__)

# In-memory rate limiting store (IP -> last submission timestamp)
# Note: This resets when the serverless function restarts, but that's acceptable
rate_limit_store = {}

def check_rate_limit(ip_address):
    """Check if an IP address has exceeded the rate limit.
    
    Args:
        ip_address: The IP address to check
    
    Returns:
        Tuple (allowed: bool, wait_time: int) - wait_time in seconds if not allowed
    """
    now = datetime.utcnow()
    rate_limit_hours = 24  # 1 submission per 24 hours per IP
    
    if ip_address in rate_limit_store:
        last_submission = rate_limit_store[ip_address]
        time_diff = now - last_submission
        required_wait = timedelta(hours=rate_limit_hours)
        
        if time_diff < required_wait:
            wait_seconds = int((required_wait - time_diff).total_seconds())
            return False, wait_seconds
    
    # Update the rate limit store
    rate_limit_store[ip_address] = now
    return True, 0


def validate_submission_data(data):
    """Validate submission data for reasonable values.
    
    Args:
        data: Dictionary with submission fields
    
    Returns:
        Tuple (valid: bool, error_message: str)
    """
    try:
        # Extract and validate sleep hours
        sleep_hours = float(data.get('sleep_hours', -1))
        if sleep_hours < 0 or sleep_hours > 24:
            return False, "Sleep hours must be between 0 and 24"
        
        # Extract and validate rest violations
        rest_violations = float(data.get('rest_violations', -1))
        if rest_violations < 0 or rest_violations > 50:
            return False, "Rest violations must be between 0 and 50"
        
        # Validate ship type
        valid_ship_types = ['Tanker', 'Bulk', 'Container', 'Gas', 'Other']
        ship_type = data.get('ship_type', '')
        if ship_type not in valid_ship_types:
            return False, f"Invalid ship type. Must be one of: {', '.join(valid_ship_types)}"
        
        # Validate region
        valid_regions = ['Global', 'Europe', 'Middle East', 'Asia', 'Africa', 'Americas']
        region = data.get('region', '')
        if region not in valid_regions:
            return False, f"Invalid region. Must be one of: {', '.join(valid_regions)}"
        
        # Validate called during rest
        valid_called = ['Yes', 'No']
        called = data.get('called_during_rest', '')
        if called not in valid_called:
            return False, "Called during rest must be 'Yes' or 'No'"
        
        # Validate port intensity
        valid_intensity = ['Low', 'Medium', 'High']
        intensity = data.get('port_intensity', '')
        if intensity not in valid_intensity:
            return False, f"Invalid port intensity. Must be one of: {', '.join(valid_intensity)}"
        
        return True, ""
    except (ValueError, TypeError) as e:
        return False, f"Invalid data format: {str(e)}"


def get_csv_files_from_github():
    """Fetch all CSV files from the submissions directory on GitHub.
    
    Returns:
        List of tuples: (filename, content)
    """
    token = os.getenv("GITHUB_TOKEN")
    repo_full_name = os.getenv("REPO_FULL_NAME")
    if not token or not repo_full_name:
        print("GITHUB_TOKEN or REPO_FULL_NAME environment variable not set.")
        return []
    
    try:
        url = f"https://api.github.com/repos/{repo_full_name}/contents/submissions"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to fetch submissions directory: {response.status_code}")
            return []
        
        files = response.json()
        csv_files = []
        
        for file_info in files:
            if file_info['name'].endswith('.csv'):
                # Fetch the file content
                file_response = requests.get(file_info['download_url'])
                if file_response.status_code == 200:
                    csv_files.append((file_info['name'], file_response.text))
        
        return csv_files
    except Exception as e:
        print(f"Error fetching CSV files: {e}")
        return []


def aggregate_submissions(csv_files):
    """Aggregate CSV submissions and calculate metrics.
    
    Args:
        csv_files: List of tuples (filename, content)
    
    Returns:
        Dictionary with aggregated data
    """
    submissions = []
    
    for filename, content in csv_files:
        try:
            reader = csv.DictReader(StringIO(content))
            for row in reader:
                submissions.append(row)
        except Exception as e:
            print(f"Error parsing {filename}: {e}")
            continue
    
    if not submissions:
        return {
            "totals": {"submissions": 0},
            "averages": {"sleepHours": 0, "restViolations": 0},
            "byShip": {},
            "byRegion": {},
            "updatedAt": datetime.utcnow().isoformat() + "+00:00"
        }
    
    # Calculate metrics
    total_submissions = len(submissions)
    total_sleep = sum(float(s.get('sleep_hours', 0)) for s in submissions)
    total_violations = sum(float(s.get('rest_violations', 0)) for s in submissions)
    
    avg_sleep = total_sleep / total_submissions if total_submissions > 0 else 0
    avg_violations = total_violations / total_submissions if total_submissions > 0 else 0
    
    # Group by ship type
    by_ship = defaultdict(int)
    for s in submissions:
        ship_type = s.get('ship_type', 'Unknown')
        by_ship[ship_type] += 1
    
    # Group by region
    by_region = defaultdict(int)
    for s in submissions:
        region = s.get('region', 'Unknown')
        by_region[region] += 1
    
    return {
        "totals": {"submissions": total_submissions},
        "averages": {
            "sleepHours": round(avg_sleep, 2),
            "restViolations": round(avg_violations, 2)
        },
        "byShip": dict(by_ship),
        "byRegion": dict(by_region),
        "updatedAt": datetime.utcnow().isoformat() + "+00:00"
    }


def commit_to_github(filename: str, content: bytes, message: str = "Add submission") -> bool:
    """Commit a file to the configured GitHub repository.

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
    
    # Check if file exists and get its SHA
    sha = None
    get_response = requests.get(url, headers=headers)
    if get_response.status_code == 200:
        sha = get_response.json().get('sha')
    
    data = {
        "message": message,
        "content": encoded_content,
        "branch": "main",
    }
    
    # Include SHA if file exists (for updates)
    if sha:
        data["sha"] = sha
    
    response = requests.put(url, json=data, headers=headers)
    if response.status_code in (201, 200):
        return True
    else:
        print(f"GitHub API returned {response.status_code}: {response.text}")
        return False


def update_aggregated_data():
    """Fetch all CSV files, aggregate them, and commit the updated data.json."""
    try:
        # Fetch all CSV files from GitHub
        csv_files = get_csv_files_from_github()
        print(f"Found {len(csv_files)} CSV files")
        
        # Aggregate the data
        aggregated_data = aggregate_submissions(csv_files)
        print(f"Aggregated {aggregated_data['totals']['submissions']} submissions")
        
        # Commit the updated data.json
        data_json = json.dumps(aggregated_data, indent=2)
        success = commit_to_github(
            'data/data.json',
            data_json.encode('utf-8'),
            f"Update aggregated data - {aggregated_data['totals']['submissions']} submissions"
        )
        
        return success
    except Exception as e:
        print(f"Error updating aggregated data: {e}")
        return False


@app.route('/upload', methods=['POST'])
def upload_file():
    """Endpoint to handle file submissions and commit them to GitHub.

    Expects a multipart/form-data POST request with a file field named
    "submission" containing a CSV file. The file will be stored in the
    `submissions/` directory of the configured repository.
    
    Security features:
    - Rate limiting: 1 submission per IP per 24 hours
    - Data validation: Checks for reasonable values
    - Honeypot detection: Rejects submissions with honeypot field filled
    """
    # Get client IP address (handle proxies)
    if request.headers.get('X-Forwarded-For'):
        ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    else:
        ip_address = request.remote_addr
    
    # Check rate limit
    allowed, wait_time = check_rate_limit(ip_address)
    if not allowed:
        hours_remaining = wait_time // 3600
        minutes_remaining = (wait_time % 3600) // 60
        return jsonify({
            'error': f'Rate limit exceeded. Please wait {hours_remaining}h {minutes_remaining}m before submitting again.'
        }), 429
    
    # Check for honeypot field (bot detection)
    honeypot_value = request.form.get('website', '')
    if honeypot_value:
        # This is likely a bot - honeypot field should be empty
        print(f"Honeypot triggered from IP: {ip_address}")
        return jsonify({'error': 'Invalid submission.'}), 400
    
    if 'submission' not in request.files:
        return jsonify({'error': 'No submission file provided.'}), 400
    
    file = request.files['submission']
    if file.filename == '':
        return jsonify({'error': 'Empty filename.'}), 400
    
    try:
        content = file.read()
        
        # Parse and validate the CSV data
        try:
            csv_content = content.decode('utf-8')
            reader = csv.DictReader(StringIO(csv_content))
            rows = list(reader)
            
            if not rows:
                return jsonify({'error': 'Empty CSV file.'}), 400
            
            # Validate the first (and should be only) row
            valid, error_msg = validate_submission_data(rows[0])
            if not valid:
                return jsonify({'error': error_msg}), 400
                
        except Exception as e:
            return jsonify({'error': f'Invalid CSV format: {str(e)}'}), 400
        
        # Proceed with committing the file
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        safe_filename = file.filename.replace("..", "_")
        target_path = f"submissions/{timestamp}_{safe_filename}"
        commit_message = f"Add submission {safe_filename} on {timestamp}"
        success = commit_to_github(target_path, content, commit_message)
        
        if success:
            # Update the aggregated data
            update_aggregated_data()
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'error': 'Failed to commit file to GitHub.'}), 500
            
    except Exception as e:
        print(f"Exception while processing upload: {e}")
        return jsonify({'error': 'Internal server error.'}), 500

# For Vercel: expose the Flask app as a WSGI callable
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
