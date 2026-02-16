import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export async function GET() {
    try {
        const logPath = path.join(process.cwd(), "..", "ng-backend", "strategy.log");

        if (!fs.existsSync(logPath)) {
            return NextResponse.json({ status: "error", message: "Log file not found" }, { status: 404 });
        }

        // Check if it's a symlink (optional, but good practice)
        // fs.lstatSync(logPath).isSymbolicLink();

        const content = fs.readFileSync(logPath, "utf-8");
        return new NextResponse(content, {
            status: 200,
            headers: {
                "Content-Type": "text/plain",
            },
        });

    } catch (error: any) {
        console.error("Error reading logs:", error);
        return NextResponse.json({ status: "error", message: error.message }, { status: 500 });
    }
}
