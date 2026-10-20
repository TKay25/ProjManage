"""WSGI entrypoint for production servers.

Gunicorn:  gunicorn --bind 0.0.0.0:$PORT 'wsgi:app'
Waitress:  waitress-serve --port=8000 wsgi:app
"""

from app import create_app

app = create_app()
