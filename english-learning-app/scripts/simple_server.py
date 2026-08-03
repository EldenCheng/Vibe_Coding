#!/usr/bin/env python3
"""
Simple HTTP Server for the Chat With Me Demo
Provides local web server to avoid browser restrictions on file:// protocol
"""

import http.server
import socketserver
import os
import sys
from pathlib import Path

# Configuration
PORT = 8000
DIRECTORY = "demo"

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler with CORS headers for better compatibility"""
    
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

def start_server(directory=DIRECTORY, port=PORT):
    """Start the HTTP server"""
    try:
        # Change to the demo directory
        if os.path.exists(directory):
            os.chdir(directory)
            print(f"📁 Serving directory: {os.path.abspath(directory)}")
        else:
            print(f"❌ Error: Directory '{directory}' not found")
            sys.exit(1)

        # Create server
        handler = CustomHTTPRequestHandler
        with socketserver.TCPServer(("", port), handler) as httpd:
            print(f"🚀 Server started successfully!")
            print(f"🌐 Open your browser and navigate to: http://localhost:{port}")
            print(f"📱 For other devices on your network, use: http://YOUR_IP:{port}")
            print(f"⚠️  Note: Speech recognition may not work on HTTP (non-localhost)")
            print(f"🛑 Press Ctrl+C to stop the server")
            print("-" * 50)
            
            # Server loop
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except OSError as e:
        # Windows下端口被占用抛出OSError(WinError 10048)，Linux下为Errno 98；
        # PermissionError也是OSError子类，统一在此处理
        print(f"❌ Error: Cannot start server on port {port}: {e}")
        print(f"   The port may be in use. Try a different port with: --port <number>")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1)

def get_local_ip():
    """Get local IP address for network access"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        return "YOUR_IP"

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Simple HTTP Server for Chat With Me Demo")
    parser.add_argument("--port", type=int, default=PORT, 
                       help=f"Port to run the server on (default: {PORT})")
    parser.add_argument("--dir", type=str, default=DIRECTORY,
                       help=f"Directory to serve (default: {DIRECTORY})")
    
    args = parser.parse_args()
    
    # Update PORT if specified
    PORT = args.port
    
    print("=" * 50)
    print("Chat With Me Demo - Web Server")
    print("=" * 50)
    print()
    
    start_server(args.dir, args.port)