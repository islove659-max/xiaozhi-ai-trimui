"""Verified TLS using the packaged CA store on stock firmware."""
import ssl

def client_ssl_context():
    import certifi
    return ssl.create_default_context(cafile=certifi.where())
