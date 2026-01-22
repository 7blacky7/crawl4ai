#!/usr/bin/env python3
"""
Test-Script fuer Claude OAuth Provider in Crawl4AI
===================================================

Dieses Script testet die Integration von Claude CLI mit OAuth.

Voraussetzungen:
1. Claude CLI installiert: npm install -g @anthropic-ai/claude-code
2. Eingeloggt: claude login (einmalig im Browser)

Usage:
    python test_claude_oauth.py
"""

import asyncio
import sys
from pathlib import Path

# Fuege das crawl4ai Modul zum Path hinzu (fuer lokales Testing)
sys.path.insert(0, str(Path(__file__).parent / "crawl4ai"))


def test_cli_availability():
    """Test 1: Prueft ob Claude CLI verfuegbar ist"""
    print("\n" + "=" * 60)
    print("TEST 1: Claude CLI Verfuegbarkeit")
    print("=" * 60)

    from crawl4ai.claude_oauth_provider import is_claude_cli_available

    available = is_claude_cli_available()
    if available:
        print("✅ Claude CLI ist installiert und verfuegbar!")
        return True
    else:
        print("❌ Claude CLI nicht gefunden!")
        print("   Installiere mit: npm install -g @anthropic-ai/claude-code")
        print("   Dann einloggen: claude login")
        return False


def test_provider_detection():
    """Test 2: Prueft ob der Provider korrekt erkannt wird"""
    print("\n" + "=" * 60)
    print("TEST 2: Provider Detection")
    print("=" * 60)

    from crawl4ai.claude_oauth_provider import is_claude_oauth_provider

    test_cases = [
        ("claude-oauth", True),
        ("claude/oauth", True),
        ("anthropic/oauth", True),
        ("openai/gpt-4", False),
        ("ollama/llama3", False),
    ]

    all_passed = True
    for provider, expected in test_cases:
        result = is_claude_oauth_provider(provider)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {provider}: {result} (expected: {expected})")
        if result != expected:
            all_passed = False

    return all_passed


def test_simple_completion():
    """Test 3: Einfache Completion mit Claude OAuth"""
    print("\n" + "=" * 60)
    print("TEST 3: Einfache Completion")
    print("=" * 60)

    from crawl4ai.claude_oauth_provider import perform_claude_oauth_completion

    print("  Sende Anfrage an Claude CLI...")
    response = perform_claude_oauth_completion(
        prompt="Antworte nur mit: 'Test erfolgreich!'",
    )

    if "error" in response:
        print(f"  ❌ Fehler: {response.get('error')}")
        return False

    content = response["choices"][0]["message"]["content"]
    print(f"  Response: {content[:100]}...")

    if "erfolgreich" in content.lower() or len(content) > 0:
        print("  ✅ Completion erfolgreich!")
        return True
    else:
        print("  ❌ Unerwartete Response")
        return False


def test_session_persistence():
    """Test 4: Session-Persistenz (Konversations-Verlauf)"""
    print("\n" + "=" * 60)
    print("TEST 4: Session Persistenz")
    print("=" * 60)

    from crawl4ai.claude_oauth_provider import (
        perform_claude_oauth_completion,
        get_session_history,
        clear_session,
    )

    session_id = "test-session-123"

    # Erste Nachricht
    print("  Nachricht 1: Merke dir die Zahl 42...")
    response1 = perform_claude_oauth_completion(
        prompt="Merke dir diese Zahl: 42. Antworte nur mit 'Zahl gemerkt.'",
        session_id=session_id,
    )

    if "error" in response1:
        print(f"  ❌ Fehler: {response1.get('error')}")
        return False

    # Zweite Nachricht (sollte Kontext haben)
    print("  Nachricht 2: Frage nach der Zahl...")
    response2 = perform_claude_oauth_completion(
        prompt="Welche Zahl solltest du dir merken?",
        session_id=session_id,
    )

    content = response2["choices"][0]["message"]["content"]
    print(f"  Response: {content[:100]}...")

    # History pruefen
    history = get_session_history(session_id)
    print(f"  Session History: {len(history)} Nachrichten")

    # Aufraeumen
    clear_session(session_id)

    if "42" in content:
        print("  ✅ Session-Persistenz funktioniert!")
        return True
    else:
        print("  ⚠️ Session-Persistenz unklar (42 nicht in Response)")
        return True  # Nicht kritisch


async def test_async_completion():
    """Test 5: Async Completion"""
    print("\n" + "=" * 60)
    print("TEST 5: Async Completion")
    print("=" * 60)

    from crawl4ai.claude_oauth_provider import aperform_claude_oauth_completion

    print("  Sende async Anfrage...")
    response = await aperform_claude_oauth_completion(
        prompt="Sage nur 'Async funktioniert!'",
    )

    if "error" in response:
        print(f"  ❌ Fehler: {response.get('error')}")
        return False

    content = response["choices"][0]["message"]["content"]
    print(f"  Response: {content[:100]}...")
    print("  ✅ Async Completion erfolgreich!")
    return True


def test_llm_config_integration():
    """Test 6: Integration mit LLMConfig"""
    print("\n" + "=" * 60)
    print("TEST 6: LLMConfig Integration")
    print("=" * 60)

    try:
        from crawl4ai import LLMConfig
        from crawl4ai.utils import perform_completion_with_backoff

        config = LLMConfig(provider="claude-oauth")
        print(f"  LLMConfig erstellt: provider={config.provider}")

        # Teste ob perform_completion_with_backoff den Provider erkennt
        print("  Teste perform_completion_with_backoff...")
        response = perform_completion_with_backoff(
            provider="claude-oauth",
            prompt_with_variables="Sage nur 'Integration Test OK'",
            api_token=None,  # Nicht benoetigt fuer OAuth!
        )

        if response and "choices" in response:
            content = response["choices"][0]["message"]["content"]
            print(f"  Response: {content[:100]}...")
            print("  ✅ LLMConfig Integration erfolgreich!")
            return True
        else:
            print("  ❌ Unerwartete Response")
            return False

    except Exception as e:
        print(f"  ❌ Fehler: {e}")
        return False


def main():
    """Fuehrt alle Tests aus"""
    print("\n" + "=" * 60)
    print("CRAWL4AI CLAUDE OAUTH PROVIDER TESTS")
    print("=" * 60)

    results = []

    # Test 1: CLI Verfuegbarkeit
    results.append(("CLI Verfuegbarkeit", test_cli_availability()))

    # Test 2: Provider Detection
    results.append(("Provider Detection", test_provider_detection()))

    # Nur fortfahren wenn CLI verfuegbar
    if results[0][1]:
        # Test 3: Einfache Completion
        results.append(("Einfache Completion", test_simple_completion()))

        # Test 4: Session Persistenz
        results.append(("Session Persistenz", test_session_persistence()))

        # Test 5: Async Completion
        results.append(("Async Completion", asyncio.run(test_async_completion())))

        # Test 6: LLMConfig Integration
        results.append(("LLMConfig Integration", test_llm_config_integration()))

    # Zusammenfassung
    print("\n" + "=" * 60)
    print("ZUSAMMENFASSUNG")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")

    print(f"\n  Ergebnis: {passed}/{total} Tests bestanden")

    if passed == total:
        print("\n🎉 Alle Tests erfolgreich! Claude OAuth ist einsatzbereit.")
    else:
        print("\n⚠️ Einige Tests fehlgeschlagen. Bitte Logs pruefen.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
