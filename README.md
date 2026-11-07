# AccessDesk

A starter user registration and admin approval app. Users register and remain pending until an admin approves them. The admin dashboard shows pending requests, users, and audit activity.

## Stack

- React + Vite frontend
- Python FastAPI backend
- MongoDB

## Run locally

1. Start MongoDB locally or create a MongoDB Atlas database.
2. In `backend`, copy `.env.example` to `.env`. Set `MONGODB_URL`, a random `JWT_SECRET` of at least 32 characters, and a unique `ADMIN_PASSWORD` of at least 16 characters. The API refuses to start with missing or short secrets.
3. Install the backend packages with `python -m pip install --user -r backend/requirements.txt`.
4. Start the API from the `backend` folder with `python -m uvicorn app:app --reload`.
5. In `frontend`, run `npm install` and `npm run dev`.

The admin account is initialized from `ADMIN_EMAIL` and `ADMIN_PASSWORD` when the API starts. `ADMIN_EMAIL` defaults to `Aditi.admin@gmail.com`; set a private admin password in `.env`. The admin password is never stored in source control. Admin sign-in is restricted to that configured account.

New user registrations must verify their email before they appear in the admin approval queue. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM` to send verification links. When `APP_ENV=development` and SMTP is not configured, the API prints a local verification link in its console. Set `APP_ENV=production` to require SMTP delivery.

Authentication endpoints have process-local rate limits. For multi-worker or multi-instance deployments, move rate-limit storage to a shared service such as Redis. Before deployment, also configure HTTPS, managed secrets, backups, monitoring, and a production MongoDB connection.

Run backend unit tests from `backend` with `python -m unittest discover -s tests -v`.
