import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { exec } from "child_process";

export async function POST(req: Request) {
    try {
        const { action } = await req.json();
        const backendDir = path.join(process.cwd(), "..", "ng-backend");
        const pidPath = path.join(backendDir, "strategy.pid");
        const scriptPath = path.join(backendDir, "start_strategy.sh");

        if (action === "start") {
            // Check if already running
            if (fs.existsSync(pidPath)) {
                const pid = fs.readFileSync(pidPath, "utf-8").trim();
                try {
                    process.kill(parseInt(pid), 0);
                    return NextResponse.json({ status: "error", message: "Service is already running" });
                } catch (e) {
                    // Stale PID, proceed to start
                }
            }

            // Execute start script
            exec(`bash ${scriptPath}`, { cwd: backendDir }, (error, stdout, stderr) => {
                if (error) {
                    console.error(`exec error: ${error}`);
                    return;
                }
                console.log(`stdout: ${stdout}`);
                console.error(`stderr: ${stderr}`);
            });

            // Give it a moment to start and create PID file
            await new Promise(resolve => setTimeout(resolve, 1000));
            return NextResponse.json({ status: "ok", message: "Service started" });

        } else if (action === "stop") {
            if (!fs.existsSync(pidPath)) {
                return NextResponse.json({ status: "error", message: "Service is not running" });
            }

            const pid = parseInt(fs.readFileSync(pidPath, "utf-8").trim());

            try {
                process.kill(pid, "SIGTERM"); // Try graceful stop
                // Wait a bit?
                // Remove PID file
                if (fs.existsSync(pidPath)) {
                    fs.unlinkSync(pidPath);
                }
                return NextResponse.json({ status: "ok", message: "Service stopped" });
            } catch (e: any) {
                return NextResponse.json({ status: "error", message: `Failed to stop service: ${e.message}` });
            }
        } else {
            return NextResponse.json({ status: "error", message: "Invalid action" }, { status: 400 });
        }

    } catch (error: any) {
        console.error("Error controlling service:", error);
        return NextResponse.json({ status: "error", message: error.message }, { status: 500 });
    }
}
