I'll update the auth handler.

```python
def login(user):
    return jwt.encode({"sub": user.id})
```

Wrote 8 lines to src/auth/handler.py. The endpoint now returns a JWT token instead of a session cookie.
