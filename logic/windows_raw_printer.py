"""Windows Raw Print - Send ESC/POS through Windows driver.

Works with existing Xprinter Windows driver - no Zadig/libusb needed.
Uses win32print to send raw bytes directly to the printer.
"""

import os
from typing import Optional


def send_raw_to_printer(
    data: bytes,
    printer_name: Optional[str] = None,
) -> bool:
    """Send raw ESC/POS data to printer via Windows driver.

    This works WITH the existing Windows printer driver - no need to
    uninstall or use Zadig/libusb.

    Args:
        data: ESC/POS command bytes
        printer_name: Exact printer name from Windows (e.g., "Xprinter XP-365B")
                       If None, uses default printer

    Returns:
        True if successfully sent to print spooler

    Example:
        >>> escpos_data = printer.generate_label("Mie Sedaap", "8886388100017", "Rp 3.200,-")
        >>> send_raw_to_printer(escpos_data, "Xprinter XP-365B")
        True
    """
    try:
        import win32print
        import win32api
        import win32con
    except ImportError:
        print("[WINDOWS_PRINT] pywin32 not installed. Install: pip install pywin32")
        return False

    try:
        # Get printer name
        if printer_name is None:
            printer_name = win32print.GetDefaultPrinter()
            print(f"[WINDOWS_PRINT] Using default printer: {printer_name}")

        # Open printer
        hPrinter = win32print.OpenPrinter(printer_name)
        try:
            # Start document
            doc_info = ("ESC/POS Label", None, "RAW")
            doc_handle = win32print.StartDocPrinter(hPrinter, 1, doc_info)

            try:
                win32print.StartPagePrinter(hPrinter)

                # Write raw bytes
                win32print.WritePrinter(hPrinter, data)

                win32print.EndPagePrinter(hPrinter)
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)

        print(f"[WINDOWS_PRINT] Sent {len(data)} bytes to {printer_name}")
        return True

    except Exception as e:
        print(f"[WINDOWS_PRINT] Error: {e}")
        return False


def list_printers() -> list:
    """List all available printers with their names.

    Returns:
        List of (printer_name, is_default) tuples
    """
    try:
        import win32print
    except ImportError:
        print("[WINDOWS_PRINT] pywin32 not installed")
        return []

    printers = []
    default = win32print.GetDefaultPrinter()

    for printer in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS):
        name = printer[2]
        printers.append((name, name == default))

    return printers


def find_xprinter() -> Optional[str]:
    """Try to find Xprinter in available printers.

    Returns:
        Printer name if found, None otherwise
    """
    printers = list_printers()

    for name, is_default in printers:
        name_lower = name.lower()
        if 'xprinter' in name_lower or 'xp-' in name_lower:
            print(f"[WINDOWS_PRINT] Found Xprinter: {name}")
            return name

    # Return default if no Xprinter found
    for name, is_default in printers:
        if is_default:
            print(f"[WINDOWS_PRINT] No Xprinter found, using default: {name}")
            return name

    return None


# ---------------------------------------------------------------------------
# Alternative: Use LPT/COM port if printer is on serial/parallel
# ---------------------------------------------------------------------------

def send_to_lpt(data: bytes, port: str = "LPT1") -> bool:
    """Send raw data to LPT/COM port (for older printers).

    Args:
        data: ESC/POS bytes
        port: Port name (LPT1, COM3, etc.)

    Returns:
        True if successful
    """
    try:
        # Windows: use \\.\ prefix for direct port access
        port_path = f"\\\\.\\{port}"

        with open(port_path, 'wb') as f:
            f.write(data)

        print(f"[WINDOWS_PRINT] Sent {len(data)} bytes to {port}")
        return True

    except Exception as e:
        print(f"[WINDOWS_PRINT] LPT error: {e}")
        return False


# ---------------------------------------------------------------------------
# Streamlit-friendly wrapper
# ---------------------------------------------------------------------------

def print_escpos_windows(
    data: bytes,
    printer_name: Optional[str] = None,
    auto_detect: bool = True,
) -> tuple[bool, str]:
    """Print ESC/POS data on Windows with automatic printer detection.

    Args:
        data: ESC/POS command bytes
        printer_name: Specific printer name (optional)
        auto_detect: Try to auto-detect Xprinter if no name given

    Returns:
        (success: bool, message: str)
    """
    if os.name != 'nt':
        return False, "Windows-only function (os.name != 'nt')"

    try:
        import win32print
    except ImportError:
        return False, "pywin32 not installed. Run: pip install pywin32"

    # Determine printer
    target_printer = printer_name
    if auto_detect and not target_printer:
        target_printer = find_xprinter()

    if not target_printer:
        return False, "No printer found. Check Windows Printers settings."

    # Try to print
    success = send_raw_to_printer(data, target_printer)

    if success:
        return True, f"Sent to {target_printer}"
    else:
        return False, f"Failed to send to {target_printer}. Check printer is online."
