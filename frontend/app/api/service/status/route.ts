import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export async function GET() {
    try {
        const pidPath = path.join(process.cwd(), "..", "ng-backend", "strategy.pid");

        if (!fs.existsSync(pidPath)) {
            return NextResponse.json({ status: "stopped", pid: null });
        }

        const pid = fs.readFileSync(pidPath, "utf-8").trim();

        // check if process is running
        try {
            process.kill(parseInt(pid), 0); // signal 0 checks existence
            return NextResponse.json({ status: "running", pid });
        } catch (e) {
            // Process not found, clean up stale PID file
            // fs.unlinkSync(pidPath); // Optional: clean up automatically? Maybe safer to just report stopped.
            return NextResponse.json({ status: "stopped", pid: null });
        }
    } catch (error: any) {
        console.error("Error checking service status:", error);
        return NextResponse.json({ status: "error", message: error.message }, { status: 500 });
    }
}
