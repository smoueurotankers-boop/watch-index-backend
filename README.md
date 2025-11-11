# Watch Index Backend for Vercel

This backend provides a simple API for uploading crew fatigue reports and committing them directly into a GitHub repository.  It is designed to run on [Vercel](https://vercel.com/) using the Python runtime and requires no long-running server.

## How It Works

- A client uploads a CSV file via a `POST` request to `/upload`.
- The function reads the file and commits it to the `submissions/` folder in your configured GitHub repository using the GitHub REST API.
- The filename includes a timestamp to ensure uniqueness.  A custom commit message is generated for each upload.
- Your existing GitHub Action in the Watch Index repository will aggregate submissions and update metrics automatically when new files are added.

## Files

- **`app.py`** – A Flask app that exposes one route (`/upload`) to handle incoming file uploads.  The Flask app is exported as `app`, which Vercel recognizes when deploying a WSGI application.
- **`requirements.txt`** – Lists the dependencies needed by the server (`Flask` and `requests`).
- **`vercel.json`** – Configures the Vercel deployment.  It specifies that `app.py` should be built using the `@vercel/python` runtime and routes requests to `/upload` to that file.

## Environment Variables

Set the following environment variables in your Vercel project:

- **`GITHUB_TOKEN`** – A personal access token with `repo` scope for the target repository.
- **`REPO_FULL_NAME`** – The full repository name (e.g. `smoueurotankers-boop/thewatchindex`) where submissions should be stored.

These can be configured in the Vercel dashboard under **Settings → Environment Variables** after you import the project.

## Deployment Steps

1. Create a new GitHub repository (e.g. `watch-index-backend`) and commit these files (`app.py`, `requirements.txt`, `vercel.json`, `README.md`).
2. Go to Vercel, log in, and create a new project by importing the repository you created in step 1.
3. During the import, set up two environment variables:
   - `GITHUB_TOKEN` – provide your personal access token.
   - `REPO_FULL_NAME` – the GitHub repository where you want to store submissions (likely the Watch Index frontend repository).
4. Deploy the project.  Vercel will build the Python app and assign it a URL (e.g. `https://watch-index-backend.vercel.app`).
5. Update your Watch Index submission form to post the CSV file to `https://your-vercel-project.vercel.app/upload`.

Once deployed, users can upload their fatigue report CSV directly from your Watch Index site and the backend will commit it into the `submissions/` folder of your repository.

## Local Testing

You can run the backend locally for testing:

```bash
export GITHUB_TOKEN=YOUR_TOKEN
export REPO_FULL_NAME=youruser/yourrepo
pip install -r requirements.txt
python app.py
```

Then send a `POST` request with a file named `submission` to `http://localhost:8000/upload`.

