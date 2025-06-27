"""MCPDoc Daemon - Python implementation for monitoring and serving llms.txt files.

This daemon monitors configuration files and automatically restarts the mcpdoc CLI
subprocess when changes are detected. It uses the mcpdoc CLI via subprocess execution
for better isolation and compatibility.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time

from pathlib import Path
from typing import Any

from platformdirs import user_config_dir
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MCPDocConfigHandler(FileSystemEventHandler):
    """File system event handler for mcpdoc configuration changes.

    This class monitors file system events and triggers server restarts
    when relevant configuration files are modified.
    """

    def __init__(self, daemon: MCPDocDaemon) -> None:
        """Initialize the file system event handler.

        :param daemon: The MCPDocDaemon instance to control
        """
        self.daemon = daemon
        self.debounce_time = 1.0
        self.last_event_time = 0

    def on_modified(self, event: Any) -> None:
        """Handle file modification events.

        :param event: The file system event
        """
        if event.is_directory:
            return

        if self._is_relevant_file(event.src_path):
            self._debounced_restart()

    def on_created(self, event: Any) -> None:
        """Handle file creation events.

        :param event: The file system event
        """
        if event.is_directory:
            return

        if self._is_relevant_file(event.src_path):
            self._debounced_restart()

    def on_deleted(self, event: Any) -> None:
        """Handle file deletion events.

        :param event: The file system event
        """
        if event.is_directory:
            return

        if self._is_relevant_file(event.src_path):
            self._debounced_restart()

    def on_moved(self, event: Any) -> None:
        """Handle file move events.

        :param event: The file system event
        """
        if event.is_directory:
            return

        is_src_relevant = self._is_relevant_file(event.src_path)
        is_dest_relevant = hasattr(event, "dest_path") and self._is_relevant_file(
            event.dest_path
        )

        if is_src_relevant or is_dest_relevant:
            self._debounced_restart()

    @staticmethod
    def _is_relevant_file(file_path: str) -> bool:
        """Check if the file is relevant for mcpdoc configuration.

        :param file_path: Path to the file to check
        :return: True if the file is a relevant configuration file, False otherwise
        """
        path = Path(file_path)
        return path.name in ("config.yaml", "config.json") or (
            path.suffix == ".txt" and path.stem.endswith(".llms")
        )

    def _debounced_restart(self) -> None:
        """Debounce rapid file changes to avoid excessive restarts.

        This method ensures that multiple rapid file changes don't trigger
        multiple server restarts by implementing a simple time-based debounce.
        """
        current_time = time.time()
        if current_time - self.last_event_time > self.debounce_time:
            self.last_event_time = current_time
            logger.info("Configuration change detected, restarting server...")
            self.daemon.restart_server()


def is_port_available(host: str, port: int) -> bool:
    """Check if a port is available on the given host.

    :param host: Host address to check
    :param port: Port number to check
    :return: True if the port is available, False otherwise
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class MCPDocDaemon:
    """Main daemon class for managing mcpdoc server with file monitoring.

    This class handles the lifecycle of the mcpdoc server, including:
    - Passing configuration files (config.yaml/config.json) to mcpdoc CLI
    - Discovering .llms.txt documentation files
    - Starting and stopping the server
    - Monitoring configuration files for changes
    """

    def __init__(
        self,
        config_dir: str | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
        transport: str = "sse",
    ) -> None:
        """Initialize the MCPDoc daemon.

        :param config_dir: Directory containing configuration and documentation files
        :param host: Host address to bind the server to
        :param port: Port to bind the server to
        :param transport: Transport method to use (sse or stdio)
        """
        self.config_dir = (
            Path(config_dir) if config_dir else Path(user_config_dir("mcpdoc"))
        )
        self.host = host
        self.port = port
        self.transport = transport
        self.process: subprocess.Popen | None = None
        self.observer: Observer | None = None
        self.running: bool = False

        # Ensure config directory exists
        self.config_dir.mkdir(exist_ok=True)

    def discover_llms_files(self) -> list[dict[str, str]]:
        """Discover all .llms.txt files in the config directory.

        :return: List of dictionaries containing name and path for each .llms.txt file
        """
        llms_files = []

        for llms_file in self.config_dir.glob("*.llms.txt"):
            name = llms_file.stem.replace(".llms", "")
            llms_files.append({"name": name, "llms_txt": str(llms_file.absolute())})

        logger.info(
            f"Discovered {len(llms_files)} LLMs files: {[f['name'] for f in llms_files]}"
        )
        return llms_files

    def build_mcpdoc_command(self) -> list[str]:
        """Build the mcpdoc CLI command with appropriate arguments.

        This method loads configuration, discovers documentation files,
        and builds the mcpdoc command line arguments.

        :return: List of command line arguments for mcpdoc
        :raises: Exception if command building fails
        """
        llms_files = self.discover_llms_files()

        if not llms_files:
            logger.warning(
                "No .llms.txt files found, server will have no documentation sources"
            )

        logger.info(f"Building command for {len(llms_files)} documentation sources")
        logger.info(f"Server will bind to: {self.host}:{self.port}")

        # Build mcpdoc command
        cmd = [sys.executable, "-m", "mcpdoc.cli"]

        # Check for config files and add appropriate flags
        config_yaml = self.config_dir / "config.yaml"
        config_json = self.config_dir / "config.json"

        if config_yaml.exists():
            cmd.extend(["--yaml", str(config_yaml.absolute())])
            logger.info(f"Using YAML config: {config_yaml}")
        elif config_json.exists():
            cmd.extend(["--json", str(config_json.absolute())])
            logger.info(f"Using JSON config: {config_json}")

        # Add URLs from discovered llms.txt files
        if llms_files:
            urls = []
            for llms_file in llms_files:
                urls.append(f"{llms_file['name']}:{llms_file['llms_txt']}")
            cmd.extend(["--urls", *urls])

        cmd.append("--follow-redirects")
        cmd.extend(["--timeout", str(10.0)])
        cmd.extend(["--allowed-domains", "*"])

        # Use specified transport
        cmd.extend(["--transport", self.transport])

        # For SSE transport, add host and port
        if self.transport == "sse":
            cmd.extend(
                [
                    "--host",
                    self.host,
                    "--port",
                    str(self.port),
                ]
            )

        cmd.extend(["--log-level", "INFO"])

        logger.info(f"MCPDoc command: {' '.join(cmd)}")
        return cmd

    def start_server(self) -> None:
        """Start the mcpdoc server as a subprocess.

        If the server is already running, this method does nothing.
        If the port is not available, it will wait and retry.

        :raises: Exception if server start fails after retries
        """
        if self.process and self.process.poll() is None:
            logger.info("Server is already running")
            return

        # Check if port is available (only for SSE transport)
        if self.transport == "sse":
            max_retries = 3
            retry_count = 0
            retry_delay = 1  # seconds

            while not is_port_available(self.host, self.port):
                retry_count += 1
                if retry_count > max_retries:
                    error_msg = (
                        f"Port {self.port} is not available after {max_retries} retries"
                    )
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)

                logger.warning(
                    f"Port {self.port} is not available, waiting {retry_delay} seconds (attempt {retry_count}/{max_retries})..."
                )
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

        try:
            cmd = self.build_mcpdoc_command()

            if self.transport == "sse":
                logger.info(
                    f"Starting mcpdoc server on {self.host}:{self.port} with SSE transport"
                )
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )
            elif self.transport == "stdio":
                # For stdio transport, redirect stdin/stdout to the subprocess
                # and ensure logs don't interfere with stdio
                logger.info("Starting mcpdoc server with stdio transport")

                # Configure logging to go to stderr only when using stdio transport
                for handler in logging.getLogger().handlers:
                    if (
                        isinstance(handler, logging.StreamHandler)
                        and handler.stream == sys.stdout
                    ):
                        handler.stream = sys.stderr

                self.process = subprocess.Popen(
                    cmd,
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
            else:
                raise ValueError(f"Unsupported transport: {self.transport}")

            logger.info(f"Server process started with PID: {self.process.pid}")

        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            raise

    def stop_server(self) -> None:
        """Stop the mcpdoc server subprocess.

        This method attempts to gracefully stop the server process.
        """
        if self.process:
            logger.info("Stopping mcpdoc server...")
            try:
                # First, try to terminate gracefully
                self.process.terminate()

                # Wait for process to terminate
                try:
                    self.process.wait(timeout=5)
                    logger.info("Server process terminated gracefully")
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "Server process did not terminate gracefully, forcing kill..."
                    )
                    self.process.kill()
                    self.process.wait()
                    logger.info("Server process killed")

            except Exception as e:
                logger.error(f"Error stopping server: {e}")

        # Clear process reference
        self.process = None

        # Wait a moment to ensure socket is released
        time.sleep(0.5)

        logger.info("Server stopped")

    def restart_server(self) -> None:
        """Restart the mcpdoc server with updated configuration.

        This method stops the current server, waits for the port to be released,
        then starts a new one. If the restart fails, it logs an error but doesn't
        raise an exception to avoid crashing the daemon.
        """
        logger.info("Restarting mcpdoc server...")
        try:
            self.stop_server()

            # Wait for port to become available with timeout
            max_wait_time = 10  # seconds
            wait_interval = 0.5  # seconds
            wait_time = 0

            while (
                not is_port_available(self.host, self.port)
                and wait_time < max_wait_time
            ):
                time.sleep(wait_interval)
                wait_time += wait_interval

            if not is_port_available(self.host, self.port):
                logger.error(
                    f"Port {self.port} is still not available after waiting {max_wait_time} seconds"
                )
                return

            self.start_server()
        except Exception as e:
            logger.error(f"Error during server restart: {e}")
            # Don't re-raise the exception to avoid crashing the daemon
            # The daemon will continue running and can try again on the next configuration change

    def start_file_monitoring(self) -> None:
        """Start monitoring the config directory for file changes.

        This method sets up a file system observer to watch for changes
        to configuration and documentation files.
        """
        event_handler = MCPDocConfigHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.config_dir), recursive=True)
        self.observer.start()
        logger.info(f"Started monitoring {self.config_dir} for configuration changes")

    def stop_file_monitoring(self) -> None:
        """Stop file monitoring.

        This method stops and cleans up the file system observer.
        """
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            logger.info("Stopped file monitoring")

    def list_configuration_files(self) -> None:
        """List all relevant configuration files found.

        This method logs information about config files and .llms.txt files
        found in the configuration directory.
        """
        logger.info("Configuration files found:")

        config_yaml = self.config_dir / "config.yaml"
        config_json = self.config_dir / "config.json"

        if config_yaml.exists():
            logger.info(f"  - {config_yaml}")
        elif config_json.exists():
            logger.info(f"  - {config_json}")
        else:
            logger.info("  - config.yaml/config.json (not found)")

        llms_files = list(self.config_dir.glob("*.llms.txt"))
        if llms_files:
            for llms_file in llms_files:
                logger.info(f"  - {llms_file}")
        else:
            logger.info("  - No .llms.txt files found")

    def run(self) -> None:
        """Main daemon loop.

        This method starts the daemon, including file monitoring and the server,
        and keeps running until interrupted.
        """
        logger.info("Starting MCPDoc Daemon")
        logger.info(f"Config directory: {self.config_dir}")
        if self.transport == "sse":
            logger.info(f"Server will bind to: {self.host}:{self.port}")
        logger.info(f"Using transport: {self.transport}")

        self.list_configuration_files()

        try:
            self.running = True
            self.start_file_monitoring()
            self.start_server()

            logger.info("MCPDoc Daemon is running. Press Ctrl+C to stop.")

            # Keep the main thread alive
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
        except Exception as e:
            logger.error(f"Daemon error: {e}")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Clean shutdown of the daemon.

        This method ensures that all resources are properly released
        when the daemon is shutting down.
        """
        logger.info("Shutting down MCPDoc Daemon...")
        self.running = False
        self.stop_file_monitoring()
        self.stop_server()
        logger.info("MCPDoc Daemon stopped")


def main() -> None:
    """Entry point for the daemon.

    This function parses command line arguments, sets up logging,
    and creates and runs the MCPDoc daemon.

    Command line arguments:
        --config-dir: Directory to monitor for configuration files
        --host: Host address to bind the server to
        --port: Port to bind the server to
        --log-level: Logging level (DEBUG, INFO, WARNING, ERROR)
        --transport: Transport method to use (sse, stdio)

    Environment variables:
        MCPDOC_CONFIG_DIR: Default config directory if --config-dir not specified
        MCPDOC_HOST: Default host if --host not specified
        MCPDOC_PORT: Default port if --port not specified
        MCPDOC_LOG_LEVEL: Default log level if --log-level not specified
        MCPDOC_TRANSPORT: Default transport if --transport not specified
    """
    import argparse

    default_config_dir = Path(user_config_dir("mcpdoc"))

    parser = argparse.ArgumentParser(
        description="MCPDoc Daemon - File monitoring mcpdoc server"
    )
    parser.add_argument(
        "--config-dir",
        default=os.environ.get("MCPDOC_CONFIG_DIR", default_config_dir),
        help=f"Directory to monitor for configuration files (default: {default_config_dir.as_posix()})",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCPDOC_HOST", "0.0.0.0"),
        help="Host to bind the server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCPDOC_PORT", "8080")),
        help="Port to bind the server to (default: 8080)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=os.environ.get("MCPDOC_LOG_LEVEL", "INFO"),
        help="Log level (default: INFO)",
    )
    parser.add_argument(
        "--transport",
        choices=["sse", "stdio"],
        default=os.environ.get("MCPDOC_TRANSPORT", "sse"),
        help="Transport method to use (default: sse)",
    )

    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Create and run daemon
    daemon = MCPDocDaemon(
        config_dir=args.config_dir,
        host=args.host,
        port=args.port,
        transport=args.transport,
    )

    daemon.run()


if __name__ == "__main__":
    main()
