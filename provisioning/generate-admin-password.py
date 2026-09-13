"""Generate a typeable bootstrap credential; never use this for machine tokens."""
import json
from pathlib import Path
import secrets
import sys


def generate(wordlist):
    words = json.loads(Path(wordlist).read_text())
    if (len(words) != 256 or len(set(words)) != 256
            or any(not isinstance(word, str) or not word.isascii()
                   or not word.isalpha() or not word.islower()
                   or not 3 <= len(word) <= 8 for word in words)):
        raise ValueError("Invalid bootstrap word list")
    # Four independent uniform choices provide 32 bits for this one-time,
    # rate-limited local bootstrap credential. Durable recovery stays longer.
    return "-".join(secrets.choice(words) for _ in range(4))


if __name__ == "__main__":
    print(generate(sys.argv[1]))
