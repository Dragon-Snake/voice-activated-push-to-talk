#!/usr/bin/env python3
"""
Build script for Mic → Push-To-Talk (Multi-Mode)
Generates standalone .exe using PyInstaller

Usage:
    python build.py                 # Standard build
    python build.py --console       # Build with console window
    python build.py --clean         # Clean build artifacts
    python build.py --debug         # Debug build
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path


class Builder:
    """PyInstaller build manager"""
    
    def __init__(self):
        self.root = Path(__file__).parent
        self.dist = self.root / "dist"
        self.build_dir = self.root / "build"
        self.spec_file = self.root / "ptt_app.spec"
        self.output_exe = self.dist / "ptt_app.exe"
    
    def clean(self):
        """Remove build artifacts"""
        print("🧹 Cleaning build artifacts...")
        
        folders_to_remove = [self.dist, self.build_dir, self.root / "__pycache__"]
        
        for folder in folders_to_remove:
            if folder.exists():
                shutil.rmtree(folder)
                print(f"  ✓ Removed: {folder.name}")
        
        # Remove build cache files
        for file in self.root.glob("*.spec"):
            if file.name != "ptt_app.spec":  # Keep our spec
                file.unlink()
        
        print("✓ Cleanup complete\n")
    
    def build(self, console=False, debug=False):
        """Build the application with PyInstaller"""
        print("🔨 Building Mic → Push-To-Talk application...\n")
        
        # Modify spec file for console if needed
        if console:
            self.modify_spec_for_console()
        
        # Build command
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            str(self.spec_file),
        ]
        
        if debug:
            cmd.append("--debug")
        
        print(f"Running: {' '.join(cmd)}\n")
        
        try:
            result = subprocess.run(cmd, check=True)
            
            if result.returncode == 0:
                print("\n" + "="*60)
                print("✅ BUILD SUCCESSFUL!")
                print("="*60)
                print(f"\nExecutable created at:")
                print(f"  {self.output_exe}\n")
                
                if self.output_exe.exists():
                    size_mb = self.output_exe.stat().st_size / (1024 * 1024)
                    print(f"File size: {size_mb:.1f} MB")
                
                print("\n📦 Distribution folder: ./dist/")
                print("🚀 Run with: ./dist/ptt_app.exe\n")
                
                return True
        
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Build failed with error code {e.returncode}")
            return False
        
        except Exception as e:
            print(f"\n❌ Build error: {e}")
            return False
    
    def modify_spec_for_console(self):
        """Modify spec file to show console window"""
        with open(self.spec_file, 'r') as f:
            content = f.read()
        
        content = content.replace("console=False", "console=True")
        
        with open(self.spec_file, 'w') as f:
            f.write(content)
        
        print("📝 Modified spec file to show console window\n")
    
    def check_dependencies(self):
        """Check if required packages are installed"""
        print("📋 Checking dependencies...\n")
        
        required = [
            'PyInstaller',
            'PySide6',
            'sounddevice',
            'numpy',
            'pynput',
        ]
        
        missing = []
        
        for package in required:
            try:
                __import__(package)
                print(f"  ✓ {package}")
            except ImportError:
                print(f"  ✗ {package} (MISSING)")
                missing.append(package)
        
        if missing:
            print(f"\n⚠️  Missing packages: {', '.join(missing)}")
            print("\nInstall with:")
            print(f"  pip install {' '.join(missing)}\n")
            return False
        
        print("\n✓ All dependencies installed\n")
        return True
    
    def run(self, console=False, debug=False, clean=False):
        """Full build workflow"""
        print("\n" + "="*60)
        print("PTT Application Builder")
        print("="*60 + "\n")
        
        if clean:
            self.clean()
        
        if not self.check_dependencies():
            print("❌ Please install missing dependencies and try again.")
            return False
        
        if not self.build(console=console, debug=debug):
            print("❌ Build failed. Check error messages above.")
            return False
        
        return True


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Build Mic → Push-To-Talk application as standalone .exe"
    )
    
    parser.add_argument(
        "--console",
        action="store_true",
        help="Show console window in built application"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build with debug information"
    )
    
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build artifacts before building"
    )
    
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only clean, don't build"
    )
    
    args = parser.parse_args()
    
    builder = Builder()
    
    if args.clean_only:
        builder.clean()
        return 0
    
    success = builder.run(
        console=args.console,
        debug=args.debug,
        clean=args.clean
    )
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
