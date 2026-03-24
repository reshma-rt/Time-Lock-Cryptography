from cryptography.fernet import Fernet

def decrypt_message(encrypted, key):
    f = Fernet(key)
    return f.decrypt(encrypted).decode()