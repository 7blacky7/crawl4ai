# ───────────────────────── terminal_routes.py ─────────────────────────
"""
Terminal WebSocket API for Crawl4AI Web UI
Provides an interactive terminal in the browser for running CLI commands.
"""

import os
import sys
import json
import asyncio
import subprocess
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/terminal", tags=["terminal"])


class TerminalSession:
    """Manages a terminal session using subprocess."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.running = False

    async def start(self) -> bool:
        """Start a new shell process."""
        try:
            # Use bash on Unix, cmd on Windows
            if sys.platform == "win32":
                shell = ["cmd.exe"]
            else:
                shell = ["/bin/bash", "-i"]

            self.process = subprocess.Popen(
                shell,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                env={**os.environ, "TERM": "xterm-256color"}
            )
            self.running = True
            return True
        except Exception as e:
            print(f"Failed to start terminal: {e}")
            return False

    async def write(self, data: str) -> None:
        """Write data to the terminal."""
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(data.encode())
                self.process.stdin.flush()
            except Exception as e:
                print(f"Write error: {e}")

    async def read(self) -> Optional[str]:
        """Read available data from the terminal."""
        if not self.process or not self.process.stdout:
            return None

        try:
            # Non-blocking read using select on Unix
            if sys.platform != "win32":
                import select
                readable, _, _ = select.select([self.process.stdout], [], [], 0.01)
                if readable:
                    data = os.read(self.process.stdout.fileno(), 4096)
                    if data:
                        return data.decode("utf-8", errors="replace")
            else:
                # Windows: try reading with timeout
                data = self.process.stdout.read1(4096) if hasattr(self.process.stdout, 'read1') else None
                if data:
                    return data.decode("utf-8", errors="replace")
        except Exception as e:
            pass

        return None

    def stop(self) -> None:
        """Stop the terminal session."""
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass
            self.process = None


@router.websocket("/ws")
async def terminal_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for terminal interaction.

    Messages:
    - { type: "input", data: "..." } - Send input to terminal
    - { type: "resize", cols: N, rows: N } - Resize terminal (not used with subprocess)

    Responses:
    - { type: "output", data: "..." } - Terminal output
    - { type: "error", data: "..." } - Error message
    """
    await websocket.accept()

    session = TerminalSession()

    try:
        if not await session.start():
            await websocket.send_json({"type": "error", "data": "Failed to start terminal"})
            await websocket.close()
            return

        await websocket.send_json({"type": "output", "data": "Terminal session started.\r\n"})

        async def read_output():
            """Background task to read terminal output."""
            while session.running:
                try:
                    output = await session.read()
                    if output:
                        await websocket.send_json({"type": "output", "data": output})
                    await asyncio.sleep(0.05)
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
                        # Resize not fully supported with subprocess
                        pass
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
