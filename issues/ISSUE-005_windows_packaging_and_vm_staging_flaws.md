# ARCHITECTURAL DECISION RECORD & DEFECT LOG
## ISSUE-005: Windows VM Packaging, Code Signing & Staging Deployment Flaws

```
Issue ID       : ISSUE-005
Title          : Windows VM Packaging, Certificate Trust & Deployment Friction
Severity       : Medium-High (Deployment UX / Staging Automation)
Component      : deployment/packaging_windows/, dist/Release100_Kiosk/
Status         : RESOLVED & DOCUMENTED
Author         : Mahendra GURAV / AI Architecture Team
Date           : September 23, 2026
Standard Ref   : GEES v1.0 Standard, Section 4 (Zero-Trust Security) & Section 2 (Verification)
```

---

## 1. Problem Statements & Root Causes

### 1.1 Defect 1: PowerShell Execution Policy `Restricted` Blocks Certificate Installation
* **Symptom:**
  Running `.\install_cert_on_vm.ps1` in standard PowerShell on a fresh Windows VM or kiosk yields:
  ```text
  .\install_cert_on_vm.ps1 : File C:\...\install_cert_on_vm.ps1 cannot be loaded because 
  running scripts is disabled on this system. For more information, see about_Execution_Policies.
  + CategoryInfo          : SecurityError: (:) [], PSSecurityException
  + FullyQualifiedErrorId : UnauthorizedAccess
  ```
* **Root Cause:**
  Windows 10/11 and Windows Server VMs default PowerShell's ExecutionPolicy to `Restricted`, which prohibits executing any raw `.ps1` script files directly from the command line without prior administrative policy modification.
* **Resolution & Hardening:**
  1. Provided a zero-PowerShell batch file `install_cert.bat` that uses the native Windows binary `certutil.exe`:
     ```cmd
     certutil -addstore -f "Root" Release100_TestCert.cer
     certutil -addstore -f "TrustedPublisher" Release100_TestCert.cer
     ```
     `certutil.exe` is a native C++ Windows utility present on 100% of Windows installations that operates independently of PowerShell execution policies.
  2. Documented the process-scoped bypass command for PowerShell users:
     ```powershell
     powershell -ExecutionPolicy Bypass -File .\install_cert_on_vm.ps1
     ```

---

### 1.2 Defect 2: Directory Distribution vs Single-File Executable Expectation
* **Symptom:**
  Deployment engineers expect the standalone `.exe` (`Release100_Kiosk.exe`) to be completely self-sufficient and copy *only* the `.exe` file across RDP/USB to the VM, leaving behind the `_internal\` folder. When launched, Windows fails with missing DLLs (`python314.dll`, OpenCV, ONNX, C-runtime).
* **Root Cause:**
  PyInstaller's default enterprise build mode is `COLLECT` (multi-binary directory). This architecture starts 10x faster than `--onefile` (which unpacks 50MB of DLLs to `%TEMP%` on every startup), but requires the sibling `_internal\` folder and `.env` to be present.
* **Resolution & Hardening:**
  1. Bundled the entire directory into `dist/KioskNode_Kiosk_Retail_v1.3.0_Portable.zip` to prevent accidental partial folder copies.
  2. Created Inno Setup script `installer_kiosk.iss` (`Release100_Kiosk_Setup_v1.3.0.exe`) which packages the entire payload into a single, self-extracting Windows installer wizard.
  3. Added explicit clarification in `VM_TESTING_GUIDE.md` that the entire `Release100_Kiosk\` folder is the unit of deployment.

---

### 1.3 Defect 3: Self-Signed Test Certificate vs Commercial Production Code Signing CA
* **Symptom:**
  Customer testing on VMs experiences certificate trust warnings unless `install_cert.bat` is executed beforehand.
* **Root Cause & Production Contrast:**
  - **Testing/Staging:** We use a free, self-generated Authenticode certificate (`CN=Release100 Industrial Automation (Test Sign), O=Apex Cold-Chain Logistics`) with SHA-256 and DigiCert RFC3161 timestamping to avoid purchasing commercial EV certificates during development. Because Microsoft does not ship our private test CA in Windows, it must be imported into the VM's Root and TrustedPublisher stores once.
  - **Commercial Production:** For live customer retail rollout, binaries must be signed with a commercial EV Code Signing Certificate (DigiCert, Sectigo) or Microsoft Azure Trusted Signing. Because Windows already trusts these public Root CAs out-of-the-box, **production customers will never install certificates or interact with PowerShell policies.**

---

## 2. Summary of Corrective Actions Implemented

| Item | File / Artifact | Corrective Action |
| :--- | :--- | :--- |
| **Batch Cert Installer** | `deployment/packaging_windows/install_cert.bat` | Uses native `certutil.exe` to bypass PowerShell `Restricted` policy completely. |
| **Kiosk Packager** | `deployment/packaging_windows/build_installer.py` | Automatically bundles `install_cert.bat`, `.env`, and batch launchers into `dist/Release100_Kiosk/` and the portable `.zip`. |
| **Installer Compiler** | `deployment/packaging_windows/installer_kiosk.iss` | Generates single-file wizard installer `Release100_Kiosk_Setup_v1.3.0.exe`. |
| **Documentation** | `dist/Release100_Kiosk/VM_TESTING_GUIDE.md` | Clear 1-click instructions for VM deployment without PowerShell friction. |
