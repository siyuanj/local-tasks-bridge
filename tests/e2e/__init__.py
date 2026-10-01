"""Hermetic end-to-end harness for the Local Tasks Bridge engine.

``fake_google`` serves the Google OAuth and Tasks v1 endpoints on 127.0.0.1,
``fake_reminders`` stands in for the two EventKit helpers on a JSON store, and
``harness`` runs the real engine CLI against both in a throwaway HOME.
"""
