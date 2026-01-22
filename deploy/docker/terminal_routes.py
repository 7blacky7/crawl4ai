# ───────────────────────── terminal_routes.py ─────────────────────────
"""
Terminal WebSocket API for Crawl4AI Web UI
Provides an interactive terminal in the browser for running CLI commands.
Uses PTY for full terminal emulation (supports interactive programs like Claude CLI).
"""

import os
import sys
import json
import asyncio
import pty
import fcntl
import struct
import termios
import signal
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/terminal", tags=["terminal"])


class PTYSession:
    """Manages a terminal session using PTY for full terminal emulation."""

    def __init__(self):
        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.running = False

    async def start(self, cols: int = 80, rows: int = 24) -> bool:
        """Start a new shell process with PTY."""
        try:
            # Create PTY pair
            self.master_fd, self.slave_fd = pty.openpty()

            # Set initial terminal size
            self._set_winsize(cols, rows)

            # Fork process
            self.pid = os.fork()

            if self.pid == 0:
                # Child process
                os.close(self.master_fd)

                # Create new session and set controlling terminal
                os.setsid()

                # Set slave as controlling terminal
                fcntl.ioctl(self.slave_fd, termios.TIOCSCTTY, 0)

                # Redirect standard streams to slave
                os.dup2(self.slave_fd, 0)  # stdin
                os.dup2(self.slave_fd, 1)  # stdout
                os.dup2(self.slave_fd, 2)  # stderr

                if self.slave_fd > 2:
                    os.close(self.slave_fd)

                # Set environment
                env = os.environ.copy()
                env['TERM'] = 'xterm-256color'
                env['COLORTERM'] = 'truecolor'

                # Execute shell
                os.execvpe('/bin/bash', ['/bin/bash', '-l'], env)
            else:
                # Parent process
                os.close(self.slave_fd)
                self.slave_fd = None

                # Set master to non-blocking
                flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
                fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                self.running = True
                return True

        except Exception as e:
            print(f"Failed to start PTY terminal: {e}")
            self._cleanup()
            return False

    def _set_winsize(self, cols: int, rows: int) -> None:
        """Set terminal window size."""
        if self.master_fd is not None:
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal."""
        self._set_winsize(cols, rows)
        # Send SIGWINCH to notify shell of resize
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGWINCH)
            except ProcessLookupError:
                pass

    async def write(self, data: str) -> None:
        """Write data to the terminal."""
        if self.master_fd is not None:
            try:
                os.write(self.master_fd, data.encode())
            except Exception as e:
                print(f"Write error: {e}")

    async def read(self) -> Optional[str]:
        """Read available data from the terminal."""
        if self.master_fd is None:
            return None

        try:
            data = os.read(self.master_fd, 4096)
            if data:
                return data.decode("utf-8", errors="replace")
        except BlockingIOError:
            # No data available (non-blocking mode)
            pass
        except OSError as e:
            if e.errno != 5:  # Ignore I/O error (happens on process exit)
                print(f"Read error: {e}")
        except Exception as e:
            pass

        return None

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except:
                pass
            self.master_fd = None

        if self.slave_fd is not None:
            try:
                os.close(self.slave_fd)
            except:
                pass
            self.slave_fd = None

    def stop(self) -> None:
        """Stop the terminal session."""
        self.running = False

        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
                os.waitpid(self.pid, 0)
            except:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                    os.waitpid(self.pid, 0)
                except:
                    pass
            self.pid = None

        self._cleanup()


@router.websocket("/ws")
async def terminal_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for terminal interaction with PTY support.

    Messages:
    - { type: "input", data: "..." } - Send input to terminal
    - { type: "resize", cols: N, rows: N } - Resize terminal

    Responses:
    - { type: "output", data: "..." } - Terminal output
    - { type: "error", data: "..." } - Error message
    """
    await websocket.accept()

    session = PTYSession()

    try:
        # Get initial size from first message if available, else use defaults
        initial_cols, initial_rows = 80, 24

        if not await session.start(initial_cols, initial_rows):
            await websocket.send_json({"type": "error", "data": "Failed to start terminal"})
            await websocket.close()
            return

        await websocket.send_json({"type": "output", "data": ""})

        async def read_output():
            """Background task to read terminal output."""
            while session.running:
                try:
                    output = await session.read()
                    if output:
                        await websocket.send_json({"type": "output", "data": output})
                    await asyncio.sleep(0.02)  # Faster polling for PTY
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    break

        # Start output reader task
        read_task = asyncio.create_task(read_output())

        try:
            while True:
                # Receive message from WebSocket
                data = await websocket.receive_text()

                try:
                    msg = json.loads(data)
                    msg_type = msg.get("type", "")

                    if msg_type == "input":
                        await session.write(msg.get("data", ""))
                    elif msg_type == "resize":
                        cols = msg.get("cols", 80)
                        rows = msg.get("rows", 24)
                        session.resize(cols, rows)
                except json.JSONDecodeError:
                    # Treat as raw input
                    await session.write(data)

        except WebSocketDisconnect:
            pass
        finally:
            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass

    finally:
        session.stop()
