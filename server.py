from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running!')

def run_server():
    server = HTTPServer(('0.0.0.0', 8080), Handler)
    server.serve_forever()

# این تابع را در bot.py صدا بزنید
def start_server():
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()