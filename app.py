from flask import Flask, request, jsonify
import os
import base64
import requests
from datetime import datetime

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
