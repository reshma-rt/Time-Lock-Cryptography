from encryption.encrypt import encrypt_message
from encryption.decrypt import decrypt_message
from secret_sharing.split_key import split_key
from secret_sharing.reconstruct_key import reconstruct_key
from time_lock.time_check import is_time_valid
from context.context_check import is_context_valid

def main():
    message = "Secret Message"
    key, encrypted = encrypt_message(message)

    shares = split_key(key, 5, 3)

    print("Encrypted:", encrypted)

    if is_time_valid() and is_context_valid():
        selected_shares = shares[:3]
        recovered_key = reconstruct_key(selected_shares)
        decrypted = decrypt_message(encrypted, recovered_key)
        print("Decrypted:", decrypted)
    else:
        print("Conditions not satisfied")

if __name__ == "__main__":
    main()