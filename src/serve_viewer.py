#!/usr/bin/env python3
"""Simple HTTP server to serve the comparison viewer HTML file."""

import http.server
import socketserver
import webbrowser
import os
from pathlib import Path

PORT = 8000


class ComparisonHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()


def main():
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    with socketserver.TCPServer(("", PORT), ComparisonHTTPRequestHandler) as httpd:
        url = f'http://localhost:{PORT}/viewer/view_comparison.html'
        print(f"Server running at {url}")
        print("Press Ctrl+C to stop the server")
        try:
            webbrowser.open(url)
        except Exception:
            pass

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == '__main__':
    main()

