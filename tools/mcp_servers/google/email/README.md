# stratova-email-mcp
SendGrid email sending + GCS template loader

## Environment Variables
- `SENDGRID_API_KEY`
- `EMAIL_TEMPLATES_BUCKET`

## Deploy
```bash
bash deploy.sh
```

## Local development
```bash
pip install -r requirements.txt
python server.py
```
