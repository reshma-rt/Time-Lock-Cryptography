from encryption.encrypt import encrypt_message
from encryption.decrypt import decrypt_message
from secret_sharing.split_key import split_key
from secret_sharing.reconstruct_key import reconstruct_key
from time_lock.time_check import is_time_valid
from context.context_check import is_context_valid

import time

print("Waiting for time lock...")
time.sleep(10)

def main():
    message = "Secret Message"

    # Step 1: Encrypt
    key, encrypted = encrypt_message(message)
    print("Encrypted:", encrypted)

    # Step 2: Split key into shares
    shares = split_key(key, total=5, required=3)

    # Step 3: Simulate user participation (3 users)
    user_shares = shares[:3]

    # Step 4: Check conditions
    if not is_time_valid():
        print("⏳ Time condition not satisfied")
        return

    if not is_context_valid():
        print("🌍 Context condition not satisfied")
        return

    # Step 5: Reconstruct key
    recovered_key = reconstruct_key(user_shares)

    # Step 6: Decrypt
    decrypted = decrypt_message(encrypted, recovered_key)
    print("✅ Decrypted:", decrypted)


if __name__ == "__main__":
    main()