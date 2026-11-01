import argparse
import os
import socket
from .config import Settings
from .errors import BridgeError
from . import __version__


def main():
    parser = argparse.ArgumentParser(description="Bridge X local gateway")
    parser.add_argument("command", nargs="?", choices=("doctor", "key", "backup"))
    parser.add_argument("--provider", choices=("molab", "fake", "openai-compatible"))
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--check-config", action="store_true", help="Check syntax without network access")
    parser.add_argument("--network", action="store_true", help="Doctor only: probe local health")
    parser.add_argument("--report", help="Doctor only: new sanitized report filename")
    parser.add_argument("--ui", action="store_true", help="Alias for --desktop")
    parser.add_argument("--desktop", action="store_true", help="Open the native proxy monitor")
    parser.add_argument("--headless", action="store_true", help="Run the proxy in the terminal")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    parser.add_argument("--output", help="Backup only: new destination filename")
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
    if args.command == "key":
        from .user_state import personal_key
        try:
            print(personal_key())  # Explicit operator command; never a startup log.
        except BridgeError as error:
            print(error.code + ": " + error.message)
            return 2
        return 0
    if args.command == "backup" and not args.output:
        parser.error("backup requires --output")
    if args.output and args.command != "backup":
        parser.error("--output requires backup")
    try:
        settings = Settings.from_env()
    except ValueError:
        print("Configuration error: invalid numeric, provider or local key setting")
        return 2
    if args.command == "backup":
        from .user_state import backup_journal
        try:
            backup_journal(settings.journal_path, args.output)
        except BridgeError as error:
            print(error.code + ": " + error.message)
            return 2
        print("Journal backup created and checked")
        return 0
    desktop = (args.desktop or args.ui) and not args.headless
    print("Bridge X " + __version__)
    print("Bridge X startup: provider=" + settings.provider + "; local config values are not printed")
    if settings.provider == "molab" and (not desktop or args.check_config):
        from .molab_provider import read_molab_config
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
    if desktop:
        try:
            from .desktop import run
            return run(settings, args.port)
        except ImportError:
            print("TK_UNAVAILABLE: Enable Tcl/Tk in your Python installation, or use --headless")
            return 2
    import uvicorn
    from .gateway import create_app
    from .observability import configure_logging
    from .paths import InstanceLock
    configure_logging()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", args.port))
    except OSError:
        listener.close()
        print("PORT_UNAVAILABLE: choose another --port or stop your own gateway")
        return 2
    try:
        with InstanceLock(settings.journal_path):
            if settings.provider == "molab" and settings.molab_tool_mode == "native":
                from .molab_runtime import ensure_native_mode
                status = ensure_native_mode(read_molab_config(settings.molab_config_path))
                print("Molab AI mode=" + status["mode"] + "; ZCode frontend tools enabled")
            port = listener.getsockname()[1]
            app = create_app(settings)
            print(f"Listening on http://127.0.0.1:{port}", flush=True)
            uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port)).run(sockets=[listener])
            return 0
    except BridgeError as error:
        print(error.code + ": " + error.message)
        return 2
    except OSError:
        print("LOCAL_STORAGE_UNAVAILABLE: check local directory permissions")
        return 2
    finally:
        listener.close()


if __name__ == "__main__":
    raise SystemExit(main())
