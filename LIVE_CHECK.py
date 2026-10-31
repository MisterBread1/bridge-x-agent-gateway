"""One live end-to-end check; does not reveal config or raw HTTP headers."""
import httpx
from bridge_x import __version__
from bridge_x.config import Settings


def main():
    base = "http://127.0.0.1:8787"
    settings = Settings.from_env()
    try:
        with httpx.Client(timeout=620, trust_env=False) as client:
            health = client.get(base + "/health", timeout=5)
            health.raise_for_status()
            status = health.json()
            print("Running bridge:", status.get("version"), "provider:", status.get("provider"))
            if status.get("version") != __version__ or status.get("provider") != "molab":
                print("ERROR: Another server is using port 8787. Close old bridge and try again.")
                return 2
            resp = client.post(base + "/v1/chat/completions", headers={"Authorization": "Bearer " + settings.local_api_key},
                               json={"model":"molab-glm","messages":[{"role":"user","content":"Ответь одним словом: привет"}],"stream":False})
            print("Bridge HTTP:", resp.status_code)
            body = resp.json()
            if resp.status_code == 200:
                choice = body.get("choices", [{}])[0]
                print("Success. Model responded. Characters:",len(str(choice.get("message", {}).get("content", ""))))
                return 0
            err = body.get("error", {})
            print("Safe code:", err.get("code", "unknown"))
            print("Safe message:", str(err.get("message", ""))[:240])
            return 1
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        print("Check failed (type only):", type(e).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
