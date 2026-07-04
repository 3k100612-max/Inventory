import cv2
from pyzbar.pyzbar import decode
import tkinter as tk
from tkinter import messagebox, ttk
import platform

# Handle cross-platform sound
if platform.system() == "Windows":
    import winsound
    def play_beep():
        winsound.Beep(1000, 200)  # Frequency 1000Hz, Duration 200ms
else:
    import os
    def play_beep():
        # Standard system beep for Mac/Linux
        print('\a') 
        # Alternatively on Mac: os.system('say "beep"')

class InventoryScanner:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw() 
        self.last_scanned = None # To prevent duplicate sounds for the same code

    def get_asset_details(self, barcode_data):
        """Creates a popup to collect status and type information."""
        dialog = tk.Toplevel()
        dialog.title(f"Asset Scanned: {barcode_data}")
        dialog.geometry("320x450")
        
        # Bring to front
        dialog.attributes('-topmost', True)
        dialog.transient(self.root)
        dialog.grab_set()

        result = {"status": None, "type": None, "accessory_detail": ""}

        # 1. Status Selection
        tk.Label(dialog, text="Select Status:", font=('Arial', 10, 'bold')).pack(pady=10)
        status_var = tk.StringVar()
        status_options = ["Returned", "Released", "Loaned", "Repair", "Retired"]
        status_combo = ttk.Combobox(dialog, textvariable=status_var, values=status_options, state="readonly")
        status_combo.pack(pady=5)
        status_combo.current(0)

        # 2. Type Selection
        tk.Label(dialog, text="Select Type:", font=('Arial', 10, 'bold')).pack(pady=10)
        type_var = tk.StringVar()
        type_options = ["Laptop", "Mobile", "Monitor", "Accessories"]
        type_combo = ttk.Combobox(dialog, textvariable=type_var, values=type_options, state="readonly")
        type_combo.pack(pady=5)
        type_combo.current(0)

        # 3. Accessory Text Field
        acc_label = tk.Label(dialog, text="Specify Accessory Type:", state="disabled")
        acc_label.pack(pady=(10, 0))
        acc_entry = tk.Entry(dialog, state="disabled")
        acc_entry.pack(pady=5)
        
        def toggle_accessory_field(event):
            if type_var.get() == "Accessories":
                acc_label.config(state="normal")
                acc_entry.config(state="normal")
            else:
                acc_label.config(state="disabled")
                acc_entry.delete(0, tk.END)
                acc_entry.config(state="disabled")
        
        type_combo.bind("<<ComboboxSelected>>", toggle_accessory_field)

        def submit():
            if type_var.get() == "Accessories" and not acc_entry.get().strip():
                messagebox.showwarning("Input Error", "Please specify the accessory type.")
                return

            result["status"] = status_var.get()
            result["type"] = type_var.get()
            result["accessory_detail"] = acc_entry.get()
            dialog.destroy()

        tk.Button(dialog, text="Submit Entry", command=submit, bg="#2ecc71", fg="white", font=('Arial', 10, 'bold')).pack(pady=30)
        
        self.root.wait_window(dialog)
        return result

    def start_scanner(self):
        cap = cv2.VideoCapture(0)
        print("Scanner active. Point camera at code. Press 'q' to quit.")

        while True:
            ret, frame = cap.read()
            if not ret: break

            detected_codes = decode(frame)
            
            for barcode in detected_codes:
                barcode_data = barcode.data.decode('utf-8')
                
                # 1. Play Sound immediately upon detection
                play_beep()
                
                # 2. Visual confirmation on screen
                (x, y, w, h) = barcode.rect
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 3)
                cv2.putText(frame, "SCANNED", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                # Show the frame so the user sees the green box before the popup
                cv2.imshow("Inventory Scanner", frame)
                cv2.waitKey(1)

                # 3. Open Data Entry Dialog
                details = self.get_asset_details(barcode_data)
                
                if details["status"]:
                    print(f"\n[LOGGED] ID: {barcode_data} | Status: {details['status']} | Type: {details['type']}")
                    if details['accessory_detail']:
                        print(f"Details: {details['accessory_detail']}")
                
                # Cooldown to prevent immediate re-scan of the same item
                cv2.waitKey(1500)

            cv2.imshow("Inventory Scanner", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    app = InventoryScanner()
    app.start_scanner()
