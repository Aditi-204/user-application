# AccessDesk

A starter user registration and admin approval app. Users register and remain pending until an admin approves them. The admin dashboard shows pending requests, users, and audit activity.

## Stack

- React + Vite frontend
- Python FastAPI backend
- MongoDB

## Run locally

1. Start MongoDB locally or create a MongoDB Atlas database.
2. In `backend`, copy `.env.example` to `.env`, set `MONGODB_URL`, and set a strong `JWT_SECRET` and admin password.
3. Install the backend packages with `python -m pip install --user -r backend/requirements.txt`.
4. Start the API from the `backend` folder with `python -m uvicorn app:app --reload`.
5. In `frontend`, run `npm install` and `npm run dev`.

The admin account is initialized from `ADMIN_EMAIL` and `ADMIN_PASSWORD` when the API starts. This is a learning project starter; before deployment, add email verification, rate limiting, HTTPS, secret management, and security review.
