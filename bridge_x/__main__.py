import argparse
import os
import socket
from .config import Settings
from . import __version__

def main():
    parser = argparse.ArgumentParser(description="Bridge X local gateway")
    parser.add_argument("command", nargs="?", choices=("doctor",))
    parser.add_argument("--provider", choices=("molab", "fake", "openai-compatible"))
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--check-config", action="store_true", help="Check local syntax without network access")
    parser.add_argument("--network", action="store_true", help="Doctor only: explicitly probe the local /health endpoint")
    parser.add_argument("--report", help="Doctor only: create a new sanitized JSON Issue report")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    if args.provider:
        os.environ['BRIDGEX_PROVIDER'] = args.provider
    if args.command == "doctor":
        from .doctor import run
        return run(args.port, args.network, args.report)
    if args.network or args.report:
        parser.error("--network and --report require doctor")
    try:
        if args.provider:
            os.environ['BRIDGEX_PROVIDER'] = args.provider
        settings = Settings.from_env()
    except ValueError:
        print("Configuration error: invalid numeric, provider or local key setting")
        return 2
    print("Bridge X " + __version__)
    print("Bridge X startup: provider=" + settings.provider + "; local config values are not printed")
    if settings.provider == "molab":
        from .molab_provider import read_molab_config
        from .errors import BridgeError
        try:
            config = read_molab_config(settings.molab_config_path)
            if any("YOUR_" in value for value in (config.chat_url, config.session_id, config.server_token)):
                raise BridgeError("MOLAB_CONFIG_PLACEHOLDER", "Replace the example values", 503)
        except BridgeError as error:
            print("Molab configuration error:", error.code)
            return 2
        print("Molab config syntax OK (upstream availability is NOT verified)")
    if args.check_config:
        print("Configuration syntax OK; upstream availability is not verified")
        return 0
    import uvicorn
    from .gateway import create_app
    from .observability import configure_logging
    configure_logging()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", args.port))
    except OSError:
        listener.close()
        print("PORT_UNAVAILABLE: choose another --port or stop your own gateway")
        return 2
    try:
        if settings.provider == "molab" and settings.molab_tool_mode == "native":
            from .molab_runtime import ensure_native_mode
            try:
                status = ensure_native_mode(read_molab_config(settings.molab_config_path))
            except BridgeError as error:
                print("Native Molab setup error:", error.code)
                return 2
            print("Molab AI mode=" + status["mode"] + "; ZCode frontend tools enabled")
        port = listener.getsockname()[1]
        print(f"Listening on http://127.0.0.1:{port}", flush=True)
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port))
        server.run(sockets=[listener])
        return 0
    finally:
        listener.close()


if __name__ == "__main__":
    raise SystemExit(main())
