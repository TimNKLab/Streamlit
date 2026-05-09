"""ESC/POS Label Printer for Xprinter thermal printers.

Generates raw ESC/POS commands for direct thermal label printing.
Bypasses PDF rasterization issues by sending binary commands directly to printer.
"""

import io
from typing import Optional, List, Dict, Any

# ESC/POS command constants
ESC = b'\x1b'
GS = b'\x1d'
FS = b'\x1c'

# Text formatting
TXT_NORMAL = ESC + b'\x21\x00'  # Normal text
TXT_BOLD_ON = ESC + b'\x45\x01'  # Bold on
TXT_BOLD_OFF = ESC + b'\x45\x00'  # Bold off
TXT_ALIGN_LEFT = ESC + b'\x61\x00'  # Left align
TXT_ALIGN_CENTER = ESC + b'\x61\x01'  # Center align
TXT_ALIGN_RIGHT = ESC + b'\x61\x02'  # Right align

# Font sizes (double width/height)
TXT_SIZE_NORMAL = ESC + b'\x21\x00'
TXT_SIZE_2W = ESC + b'\x21\x20'  # Double width
TXT_SIZE_2H = ESC + b'\x21\x10'  # Double height
TXT_SIZE_2X = ESC + b'\x21\x30'  # Double width & height

# Line spacing and feed
LINE_FEED = b'\x0a'
FEED_LINES = lambda n: ESC + bytes([0x64, n])  # Feed n lines
CUT_PAPER = GS + b'\x56\x00'  # Partial cut

# Barcode commands
BARCODE_HEIGHT = GS + b'\x68'  # + height in dots
BARCODE_WIDTH = GS + b'\x77'   # + width 2-6
BARCODE_HRI_POS = GS + b'\x48'  # + 0=none, 1=above, 2=below, 3=both
BARCODE_PRINT = GS + b'\x6b'   # + type + data + NUL

# Barcode types
BARCODE_CODE128 = 73  # Code 128

# Printer initialization
INIT_PRINTER = ESC + b'\x40'


class ESCPOSLabelPrinter:
    """Generate ESC/POS commands for price label printing on thermal printers.
    
    Designed for 28mm x 18mm labels on Xprinter thermal printers.
    Uses Code 128 barcodes which are widely supported.
    """
    
    # Label dimensions in dots (203 DPI typical for thermal printers)
    # 28mm = ~223 dots, 18mm = ~143 dots at 203 DPI
    LABEL_WIDTH_DOTS = 224  # 28mm @ 203 DPI
    LABEL_HEIGHT_DOTS = 144  # 18mm @ 203 DPI
    
    def __init__(self):
        self.buffer = io.BytesIO()
    
    def _write(self, data: bytes):
        """Write raw bytes to buffer."""
        self.buffer.write(data)
    
    def _write_text(self, text: str, encoding: str = 'cp437'):
        """Write text with specified encoding (CP437 for Epson compatibility)."""
        try:
            self._write(text.encode(encoding))
        except UnicodeEncodeError:
            # Fallback to ascii with replacement
            self._write(text.encode('ascii', errors='replace'))
    
    def reset(self):
        """Initialize/reset printer to default state."""
        self._write(INIT_PRINTER)
        return self
    
    def set_align(self, align: str = 'center'):
        """Set text alignment."""
        if align == 'left':
            self._write(TXT_ALIGN_LEFT)
        elif align == 'right':
            self._write(TXT_ALIGN_RIGHT)
        else:
            self._write(TXT_ALIGN_CENTER)
        return self
    
    def set_bold(self, bold: bool = True):
        """Enable/disable bold text."""
        self._write(TXT_BOLD_ON if bold else TXT_BOLD_OFF)
        return self
    
    def set_size(self, size: str = 'normal'):
        """Set text size."""
        sizes = {
            'normal': TXT_SIZE_NORMAL,
            '2w': TXT_SIZE_2W,
            '2h': TXT_SIZE_2H,
            '2x': TXT_SIZE_2X,
        }
        self._write(sizes.get(size, TXT_SIZE_NORMAL))
        return self
    
    def feed(self, lines: int = 1):
        """Feed paper by N lines."""
        self._write(FEED_LINES(lines))
        return self
    
    def newline(self):
        """Line feed."""
        self._write(LINE_FEED)
        return self
    
    def text(self, text: str, align: str = 'center', bold: bool = False, size: str = 'normal'):
        """Write text with formatting."""
        self.set_align(align)
        self.set_bold(bold)
        self.set_size(size)
        self._write_text(text)
        self.newline()
        return self
    
    def barcode(self, data: str, height: int = 64, width: int = 2, hri: int = 2):
        """Print Code 128 barcode.
        
        Args:
            data: Barcode data (digits and alphanumeric for Code 128)
            height: Barcode height in dots (default 64 = ~8mm)
            width: Barcode module width 2-6 (default 2)
            hri: Human readable interpretation position
                 0=none, 1=above, 2=below, 3=both
        """
        # Set barcode height
        self._write(BARCODE_HEIGHT + bytes([height]))
        # Set barcode width
        self._write(BARCODE_WIDTH + bytes([width]))
        # Set HRI position
        self._write(BARCODE_HRI_POS + bytes([hri]))
        
        # Print barcode (Code 128)
        # Format: GS k type length data NUL
        # For type 73 (Code 128), data is raw bytes
        barcode_data = data.encode('ascii')
        self._write(BARCODE_PRINT + bytes([BARCODE_CODE128, len(barcode_data)]) + barcode_data)
        return self
    
    def cut(self):
        """Cut paper (for label mode, this may eject or mark cut position)."""
        self._write(CUT_PAPER)
        return self
    
    def label_mode_start(self):
        """Initialize printer for label printing mode.
        
        Sets up continuous label mode with proper margins.
        """
        self.reset()
        # Set line spacing to minimum for compact labels
        self._write(ESC + b'\x33\x00')  # Set line spacing to 0
        return self
    
    def label_mode_end(self):
        """Finalize label and feed to cut position."""
        self.feed(2)  # Feed slightly to ensure label is fully printed
        return self
    
    def generate_label(
        self,
        name: str,
        barcode: str,
        price: str,
        max_name_len: int = 20,
    ) -> bytes:
        """Generate a complete price label with product info.
        
        Layout for 28mm x 18mm label (224x144 dots @ 203 DPI):
        - Product name (top, small, bold, centered, truncated)
        - Barcode (center, with HRI below)
        - Price (bottom, large, bold, centered)
        
        Args:
            name: Product name (will be truncated if too long)
            barcode: Barcode number (numeric string)
            price: Formatted price string (e.g., "Rp 12.500,-")
            max_name_len: Maximum characters for product name
        
        Returns:
            ESC/POS command bytes ready to send to printer
        """
        self.buffer = io.BytesIO()  # Reset buffer
        
        # Initialize
        self.label_mode_start()
        
        # Product name (compact, bold, centered)
        display_name = name[:max_name_len] if len(name) > max_name_len else name
        self.text(display_name, align='center', bold=True, size='normal')
        
        # Small feed
        self.feed(1)
        
        # Barcode with human-readable text below
        # Height 48 dots = ~6mm, width 2 for compact but scannable
        self.set_align('center')
        self.barcode(barcode, height=48, width=2, hri=2)
        self.newline()
        
        # Small feed before price
        self.feed(1)
        
        # Price (large, bold, centered) - double height for visibility
        self.text(price, align='center', bold=True, size='2h')
        
        # Finalize
        self.label_mode_end()
        
        return self.buffer.getvalue()
    
    def generate_labels_batch(
        self,
        items: List[Dict[str, Any]],
        price_formatter: Optional[Any] = None,
    ) -> bytes:
        """Generate multiple labels as a batch.
        
        Args:
            items: List of dicts with 'name', 'barcode', 'het' keys
            price_formatter: Optional callable to format price (e.g., lambda p: f"Rp {p:,}")
        
        Returns:
            ESC/POS command bytes for all labels
        """
        self.buffer = io.BytesIO()
        
        self.label_mode_start()
        
        for idx, item in enumerate(items):
            name = str(item.get('name', '')).strip()
            barcode = str(item.get('barcode', '')).strip()
            het = item.get('het')
            
            if not name or not barcode:
                continue
            
            # Format price
            if price_formatter and het is not None:
                price_str = price_formatter(het)
            elif het is not None:
                price_str = f"Rp {het:,.0f},-".replace(',', '.')
            else:
                price_str = "Rp -,-"
            
            # Add label gap between labels (except first)
            if idx > 0:
                # Form feed or extra line feeds for label gap
                self.feed(5)  # Adjust based on label gap requirements
            
            # Product name
            display_name = name[:20] if len(name) > 20 else name
            self.text(display_name, align='center', bold=True, size='normal')
            self.feed(1)
            
            # Barcode
            self.set_align('center')
            self.barcode(barcode, height=48, width=2, hri=2)
            self.newline()
            self.feed(1)
            
            # Price
            self.text(price_str, align='center', bold=True, size='2h')
        
        self.label_mode_end()
        
        return self.buffer.getvalue()
    
    def get_bytes(self) -> bytes:
        """Get current buffer contents."""
        return self.buffer.getvalue()


# ---------------------------------------------------------------------------
# USB Printer Interface (requires pyusb)
# ---------------------------------------------------------------------------

def send_to_usb_printer(
    data: bytes,
    vendor_id: int = 0x0416,  # Xprinter common VID
    product_id: int = 0x5011,  # Xprinter common PID
    endpoint: int = 0x01,
) -> bool:
    """Send ESC/POS data to USB thermal printer using pyusb.
    
    Args:
        data: ESC/POS command bytes
        vendor_id: USB vendor ID (default 0x0416 for Xprinter)
        product_id: USB product ID (default 0x5011 for Xprinter)
        endpoint: USB endpoint address for bulk out
    
    Returns:
        True if successful, False otherwise
    
    Note:
        This requires pyusb and appropriate USB permissions.
        On Windows, may need libusbK driver installed for the printer.
        On Linux, may need udev rules for usb access.
    """
    try:
        import usb.core
        import usb.util
    except ImportError:
        print("[ESC/POS] pyusb not installed. Install with: pip install pyusb")
        return False
    
    try:
        # Find device
        dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if dev is None:
            print(f"[ESC/POS] Printer not found (VID={vendor_id:04x}, PID={product_id:04x})")
            return False
        
        # Get active configuration
        cfg = dev.get_active_configuration()
        
        # Find bulk out endpoint
        intf = usb.util.find_descriptor(cfg, bInterfaceClass=7)  # Printer class
        if intf is None:
            # Try first interface
            intf = cfg[(0, 0)]
        
        ep = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: 
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        
        if ep is None:
            print("[ESC/POS] No suitable endpoint found")
            return False
        
        # Detach kernel driver if needed (Linux)
        if dev.is_kernel_driver_active(intf.bInterfaceNumber):
            dev.detach_kernel_driver(intf.bInterfaceNumber)
        
        # Send data in chunks
        chunk_size = 4096
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            ep.write(chunk)
        
        print(f"[ESC/POS] Sent {len(data)} bytes to printer")
        return True
        
    except Exception as e:
        print(f"[ESC/POS] USB error: {e}")
        return False


def save_to_file(data: bytes, filepath: str) -> bool:
    """Save ESC/POS data to file for debugging or raw printing.
    
    Args:
        data: ESC/POS command bytes
        filepath: Output file path
    
    Returns:
        True if saved successfully
    """
    try:
        with open(filepath, 'wb') as f:
            f.write(data)
        print(f"[ESC/POS] Saved {len(data)} bytes to {filepath}")
        return True
    except Exception as e:
        print(f"[ESC/POS] Save error: {e}")
        return False


def find_printer_devices():
    """Find all USB printer devices.
    
    Returns:
        List of (vendor_id, product_id, manufacturer, product) tuples
    """
    try:
        import usb.core
    except ImportError:
        print("[ESC/POS] pyusb not installed")
        return []
    
    devices = []
    for dev in usb.core.find(find_all=True, bDeviceClass=7):  # Printer class
        try:
            vid = dev.idVendor
            pid = dev.idProduct
            
            # Try to get string descriptors
            try:
                mfg = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else "Unknown"
                prod = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else "Unknown"
            except:
                mfg = "Unknown"
                prod = "Unknown"
            
            devices.append((vid, pid, mfg, prod))
        except:
            pass
    
    return devices
