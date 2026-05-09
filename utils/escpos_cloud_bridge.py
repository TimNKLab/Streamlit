"""ESC/POS Cloud Printing Bridge via Web Serial API.

Enables direct thermal printing from Streamlit Cloud deployments by using
the browser's Web Serial API to send ESC/POS commands to local USB printer.

Requirements:
- Chrome/Edge 89+ (Web Serial API support)
- HTTPS or localhost (secure context required)
- User grants USB permission via browser picker
"""

import base64
import json
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import streamlit as st
import streamlit.components.v1 as components

# Component path
COMPONENT_PATH = Path(__file__).parent.parent / "components" / "escpos_serial_bridge.html"


class ESCPOSCloudBridge:
    """Bridge to send ESC/POS commands via browser Web Serial API.
    
    This allows cloud-deployed Streamlit apps to print to local USB thermal
    printers by delegating the USB communication to the browser via Web Serial API.
    
    Usage:
        bridge = ESCPOSCloudBridge()
        
        # Check if browser supports Web Serial
        if bridge.is_supported():
            # Embed the bridge component
            bridge.embed(height=200)
            
            # Print ESC/POS data
            result = bridge.print(escpos_bytes)
            if result['success']:
                st.success("Sent to printer!")
    """
    
    def __init__(self, key: str = "escpos_bridge"):
        self.key = key
        self._component_value = None
        
    def is_supported(self) -> bool:
        """Check if browser supports Web Serial API.
        
        Note: This is a client-side check. Use embed() with a callback
        to get actual browser capability.
        """
        return True  # Actual check happens in browser
    
    def embed(
        self,
        height: int = 250,
        on_status: Optional[Callable[[Dict], None]] = None,
    ) -> Optional[Dict]:
        """Embed the ESC/POS Serial Bridge component.
        
        This creates an iframe with the Web Serial bridge that can communicate
        with the USB printer. Users must click "Select Printer" to grant permission.
        
        Args:
            height: Height of component iframe in pixels
            on_status: Optional callback for status updates from bridge
            
        Returns:
            Component return value (last message from bridge)
        """
        if not COMPONENT_PATH.exists():
            st.error("ESC/POS bridge component not found. Check installation.")
            return None
        
        # Read HTML content
        html_content = COMPONENT_PATH.read_text(encoding='utf-8')
        
        # Inject JavaScript to communicate with Streamlit
        js_bridge = """
        <script>
            // Streamlit communication bridge
            (function() {
                const BRIDGE_KEY = 'escpos_bridge_state';
                
                // Store last message for Streamlit to read
                window.addEventListener('message', (event) => {
                    if (event.data && event.data.type) {
                        // Store in sessionStorage for Streamlit component value
                        const state = {
                            timestamp: Date.now(),
                            data: event.data
                        };
                        sessionStorage.setItem(BRIDGE_KEY, JSON.stringify(state));
                        
                        // Also try to send to Streamlit if parent allows
                        if (window.parent !== window) {
                            try {
                                window.parent.postMessage({
                                    type: 'streamlit:componentValue',
                                    value: event.data
                                }, '*');
                            } catch (e) {}
                        }
                    }
                });
                
                // Function called by Streamlit to send data to iframe
                window.sendToPrinter = function(base64Data) {
                    const iframe = document.getElementById('escpos-bridge-iframe');
                    if (iframe && iframe.contentWindow) {
                        iframe.contentWindow.postMessage({
                            type: 'QUICK_PRINT',
                            base64Data: base64Data
                        }, '*');
                        return true;
                    }
                    return false;
                };
            })();
        </script>
        """
        
        # Wrap HTML in iframe for isolation
        html_with_iframe = f"""
        {js_bridge}
        <iframe 
            id="escpos-bridge-iframe"
            srcdoc="{html_content.replace('"', '&quot;')}" 
            width="100%" 
            height="{height}px"
            style="border: 1px solid #ddd; border-radius: 8px;"
            sandbox="allow-scripts allow-same-origin"
        ></iframe>
        """
        
        # Render component
        # NOTE: `st.components.v1.html()` does not accept a `key` argument in
        # some Streamlit versions; passing it raises:
        # IframeMixin._html() got an unexpected keyword argument 'key'
        result = components.html(html_with_iframe, height=height)
        
        return result
    
    def print_direct(self, escpos_data: bytes) -> Dict[str, Any]:
        """Send ESC/POS data to printer via Web Serial bridge.
        
        This embeds a minimal bridge that auto-triggers printing.
        
        Args:
            escpos_data: Raw ESC/POS command bytes
            
        Returns:
            Dict with 'success' boolean and optional 'error' message
        """
        if not COMPONENT_PATH.exists():
            return {'success': False, 'error': 'Bridge component not found'}
        
        # Encode data to base64 for safe transmission
        b64_data = base64.b64encode(escpos_data).decode('ascii')
        
        # Create auto-print HTML that immediately prompts for printer
        auto_print_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <script>
                const ESCPOS_DATA = "{b64_data}";
                let port = null;
                let writer = null;
                
                async function quickPrint() {{
                    if (!('serial' in navigator)) {{
                        reportResult(false, 'Web Serial API not supported. Use Chrome/Edge 89+ with HTTPS.');
                        return;
                    }}
                    
                    try {{
                        // Request port (shows browser picker)
                        const filters = [
                            {{ usbVendorId: 0x0416 }}, // Xprinter
                            {{ usbVendorId: 0x04b8 }}, // Epson
                            {{ usbVendorId: 0x1504 }}, // Bixolon
                            {{ usbVendorId: 0x0519 }}, // Star
                        ];
                        
                        port = await navigator.serial.requestPort({{ filters }});
                        await port.open({{ baudRate: 9600 }});
                        writer = port.writable.getWriter();
                        
                        // Decode and send
                        const binaryString = atob(ESCPOS_DATA);
                        const data = new Uint8Array(binaryString.length);
                        for (let i = 0; i < binaryString.length; i++) {{
                            data[i] = binaryString.charCodeAt(i);
                        }}
                        
                        // Send in chunks
                        const CHUNK_SIZE = 64;
                        let sent = 0;
                        while (sent < data.length) {{
                            const chunk = data.slice(sent, sent + CHUNK_SIZE);
                            await writer.write(chunk);
                            sent += chunk.length;
                        }}
                        
                        reportResult(true, `Sent ${{data.length}} bytes to printer`);
                        
                        // Cleanup
                        await writer.close();
                        await port.close();
                        
                    }} catch (error) {{
                        if (error.name === 'NotFoundError') {{
                            reportResult(false, 'No printer selected');
                        }} else {{
                            reportResult(false, error.message);
                        }}
                    }}
                }}
                
                function reportResult(success, message) {{
                    const result = {{
                        success: success,
                        message: message,
                        timestamp: new Date().toISOString()
                    }};
                    
                    // Store for Streamlit to read
                    sessionStorage.setItem('escpos_print_result', JSON.stringify(result));
                    
                    // Display
                    document.getElementById('result').textContent = 
                        success ? '✅ ' + message : '❌ ' + message;
                    document.getElementById('result').className = 
                        success ? 'success' : 'error';
                }}
                
                // Do NOT auto-start on load; must be triggered by user gesture.
            </script>
            <style>
                body {{ font-family: sans-serif; padding: 20px; text-align: center; }}
                #result {{ padding: 15px; border-radius: 8px; margin: 10px 0; font-weight: bold; }}
                .success {{ background: #d4edda; color: #155724; }}
                .error {{ background: #f8d7da; color: #721c24; }}
                .info {{ color: #666; font-size: 12px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div id="result">Click the button to select printer and print.</div>
            <button onclick="quickPrint()" style="padding: 10px 20px; cursor: pointer;">
                🔌 Select Printer & Print
            </button>
            <div class="info">
                <p>Click the button above to select your USB printer device.</p>
                <p>Requires Chrome/Edge with HTTPS or localhost.</p>
            </div>
        </body>
        </html>
        """
        
        # Display as component
        # See note in embed(): avoid passing unsupported `key`.
        components.html(auto_print_html, height=180)
        
        return {
            'success': True,
            'message': 'Component shown. Click "Select Printer & Print" inside it to open the USB permission prompt.'
        }
    
    def render_controls(self) -> None:
        """Render full bridge controls with status display."""
        st.subheader("🔌 ESC/POS Cloud Printer Bridge")
        
        info_col1, info_col2 = st.columns([2, 1])
        with info_col1:
            st.info("""
            **Cloud Printing via Web Serial API**
            
            This allows direct USB printing even when Streamlit runs in the cloud.
            Your browser sends ESC/POS commands directly to the printer.
            
            **Requirements:**
            - Chrome or Edge browser (v89+)
            - HTTPS or localhost connection
            - Grant USB permission when prompted
            """)
        with info_col2:
            st.caption("Supported Printers:")
            st.markdown("""
            - Xprinter (0x0416)
            - Epson (0x04b8)
            - Bixolon (0x1504)
            - Star (0x0519)
            """)
        
        # Embed the bridge
        self.embed(height=250)


def print_escpos_cloud(escpos_data: bytes, key: str = "escpos_print") -> bool:
    """Quick print function for cloud deployments.
    
    Usage in Streamlit app:
        if st.button("Print to USB"):
            escpos_bytes = service.generate_escpos_labels(items)
            success = print_escpos_cloud(escpos_bytes)
    
    Args:
        escpos_data: Raw ESC/POS command bytes
        key: Component key for Streamlit
        
    Returns:
        True if print dialog was opened
    """
    bridge = ESCPOSCloudBridge(key=key)
    result = bridge.print_direct(escpos_data)
    return result.get('success', False)


def check_cloud_print_support() -> Dict[str, Any]:
    """Check if current environment supports cloud printing.
    
    Returns dict with:
        - supported: bool (always True, actual check is client-side)
        - requirements: List of requirements
        - instructions: User instructions
    """
    return {
        'supported': True,  # Actual check happens in browser
        'requirements': [
            'Chrome or Edge browser (version 89 or newer)',
            'HTTPS connection or localhost',
            'USB printer connected to client machine',
            'User must grant USB permission'
        ],
        'instructions': 
            'When you click Print, your browser will show a USB device picker. '
            'Select your Xprinter device to send ESC/POS commands directly.'
    }
