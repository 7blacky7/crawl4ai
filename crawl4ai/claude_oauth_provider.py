"""
Claude OAuth Provider for Crawl4AI
===================================
Ermoeglicht die Nutzung von Claude CLI mit OAuth-Authentifizierung
anstelle von API-Keys. Perfekt fuer Max-Abo Nutzer.

WICHTIG:
- Claude CLI muss installiert sein: npm install -g @anthropic-ai/claude-code
- Einmalig einloggen: claude login
- Dann funktioniert alles automatisch via OAuth!

Verwendung:
    from crawl4ai import LLMConfig
    from crawl4ai.claude_oauth_provider import perform_claude_oauth_completion

    # Als Provider "claude-oauth" verwenden
    config = LLMConfig(provider="claude-oauth")
"""

import subprocess
import os
import asyncio
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class Message:
    """Nachricht im Conversation-Verlauf"""
    role: str  # 'user' oder 'assistant'
    content: str
    timestamp: datetime


@dataclass
class SessionState:
    """Session-Zustand fuer persistente Konversationen"""
    messages: List[Message]
    token_count: int
    is_active: bool


# Konfiguration
TOKEN_LIMIT = 200000    # Max Context Window
TOKEN_WARNING = 180000  # Warnung bei Annaeherung
MAX_HISTORY = 20        # Max Messages im Context

# Session Storage (in-memory, fuer Persistenz Redis/Qdrant nutzen)
_sessions: Dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState:
    """Holt oder erstellt eine Session"""
    if session_id not in _sessions:
        _sessions[session_id] = SessionState(
            messages=[],
            token_count=0,
            is_active=True
        )
    return _sessions[session_id]


def build_context_string(messages: List[Message]) -> str:
    """Baut den Konversations-Kontext als String"""
    recent = messages[-MAX_HISTORY:]
    if not recent:
        return ''

    context = '\n--- CONVERSATION HISTORY ---\n'
    for msg in recent:
        role = 'User' if msg.role == 'user' else 'Assistant'
        content = msg.content[:2000] + '...[truncated]' if len(msg.content) > 2000 else msg.content
        context += f'{role}: {content}\n\n'
    context += '--- END HISTORY ---\n\n'

    return context


def is_claude_cli_available() -> bool:
    """Prueft ob Claude CLI installiert und verfuegbar ist"""
    try:
        result = subprocess.run(
            ['claude', '--version'],
            capture_output=True,
            text=True,
            timeout=10,
            shell=True
        )
        return result.returncode == 0
    except Exception:
        return False


def perform_claude_oauth_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    json_response: bool = False,
    on_chunk: Optional[Callable[[str], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Fuehrt eine Completion mit Claude CLI via OAuth durch.

    KRITISCH: Der ANTHROPIC_API_KEY wird aus den Environment-Variablen entfernt,
    damit die CLI automatisch OAuth verwendet!

    Args:
        prompt: Die User-Nachricht
        system_prompt: Optionaler System-Prompt
        session_id: Optional fuer persistente Sessions
        json_response: Ob JSON-Output erwartet wird
        on_chunk: Callback fuer Streaming
        **kwargs: Weitere Parameter (ignoriert fuer Kompatibilitaet)

    Returns:
        Dict mit 'choices' im LiteLLM-kompatiblen Format
    """

    # Session handling
    session = None
    if session_id:
        session = get_session(session_id)
        if not session.is_active:
            return _create_error_response('Session ist nicht mehr aktiv.')

        # User Message speichern
        session.messages.append(Message(
            role='user',
            content=prompt,
            timestamp=datetime.now()
        ))

    # Prompt zusammenbauen
    full_prompt = ''
    if system_prompt:
        full_prompt += f'{system_prompt}\n\n'

    if session and session.messages:
        history = build_context_string(session.messages[:-1])  # Ohne aktuelle Nachricht
        full_prompt += history

    full_prompt += f'User: {prompt}'

    # JSON-Mode Instruktion
    if json_response:
        full_prompt += '\n\nIMPORTANT: Respond ONLY with valid JSON, no additional text.'

    # =========================================
    # KRITISCH: API-Key entfernen!
    # Damit CLI automatisch OAuth nutzt
    # =========================================
    env = os.environ.copy()
    if 'ANTHROPIC_API_KEY' in env:
        del env['ANTHROPIC_API_KEY']

    try:
        # Claude CLI ausfuehren
        process = subprocess.Popen(
            ['claude', '--print'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True,
            env=env
        )

        # Prompt senden
        stdout, stderr = process.communicate(input=full_prompt, timeout=120)

        if process.returncode != 0 and not stdout.strip():
            error_msg = stderr[:500] if stderr else f'Exit code: {process.returncode}'
            return _create_error_response(f'Claude CLI Error: {error_msg}')

        response_text = stdout.strip() or '[No response from Claude]'

        # Session aktualisieren
        if session:
            session.messages.append(Message(
                role='assistant',
                content=response_text,
                timestamp=datetime.now()
            ))

            # Token-Schaetzung (~4 chars = 1 token)
            tokens = (len(prompt) + len(response_text)) // 4
            session.token_count += tokens

            if session.token_count >= TOKEN_LIMIT:
                print(f'[Claude OAuth] TOKEN LIMIT REACHED - Rotation needed!')
            elif session.token_count >= TOKEN_WARNING:
                print(f'[Claude OAuth] Token warning: {session.token_count}')

        # LiteLLM-kompatibles Response-Format
        return _create_success_response(response_text)

    except subprocess.TimeoutExpired:
        return _create_error_response('Claude CLI Timeout (120s)')
    except FileNotFoundError:
        return _create_error_response(
            'Claude CLI nicht gefunden. Installiere mit: npm install -g @anthropic-ai/claude-code'
        )
    except Exception as e:
        return _create_error_response(f'Claude CLI Error: {str(e)}')


async def aperform_claude_oauth_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    json_response: bool = False,
    on_chunk: Optional[Callable[[str], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Async Version der Claude OAuth Completion.
    Fuehrt den Subprocess in einem Thread aus.
    """
    return await asyncio.to_thread(
        perform_claude_oauth_completion,
        prompt,
        system_prompt,
        session_id,
        json_response,
        on_chunk,
        **kwargs
    )


def _create_success_response(content: str) -> Dict[str, Any]:
    """Erstellt ein LiteLLM-kompatibles Success-Response"""
    return {
        'choices': [{
            'message': {
                'content': content,
                'role': 'assistant'
            },
            'index': 0,
            'finish_reason': 'stop'
        }],
        'model': 'claude-oauth',
        'usage': {
            'prompt_tokens': 0,  # Nicht verfuegbar bei CLI
            'completion_tokens': 0,
            'total_tokens': 0
        }
    }


def _create_error_response(error: str) -> Dict[str, Any]:
    """Erstellt ein Error-Response"""
    return {
        'choices': [{
            'message': {
                'content': f'Error: {error}',
                'role': 'assistant'
            },
            'index': 0,
            'finish_reason': 'error'
        }],
        'model': 'claude-oauth',
        'error': error
    }


# Session Management Funktionen
def get_session_history(session_id: str) -> List[Dict]:
    """Holt die Session-History"""
    session = _sessions.get(session_id)
    if not session:
        return []
    return [
        {'role': m.role, 'content': m.content, 'timestamp': m.timestamp.isoformat()}
        for m in session.messages
    ]


def clear_session(session_id: str) -> None:
    """Loescht eine Session"""
    if session_id in _sessions:
        del _sessions[session_id]
        print(f'[Claude OAuth] Session {session_id} cleared')


def list_sessions() -> List[str]:
    """Listet alle aktiven Sessions"""
    return list(_sessions.keys())


# Fuer Integration in crawl4ai's perform_completion_with_backoff
def is_claude_oauth_provider(provider: str) -> bool:
    """Prueft ob der Provider Claude OAuth ist"""
    return provider.lower() in ('claude-oauth', 'claude/oauth', 'anthropic/oauth')
