import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';

export async function GET() {
    try {
        const backendDir = path.resolve(process.cwd(), '../ng-backend');
        const logsPath = path.join(backendDir, 'trading_logs.json');

        if (fs.existsSync(logsPath)) {
            const data = fs.readFileSync(logsPath, 'utf-8');
            return new NextResponse(data, {
                status: 200,
                headers: {
                    'Content-Type': 'application/json',
                },
            });
        } else {
            return NextResponse.json({ date: new Date().toISOString().split('T')[0], "今日总收益率": "0.00%", logs: [] });
        }
    } catch (error: any) {
        console.error('Error reading trading logs:', error);
        return NextResponse.json({ status: 'error', message: error.message }, { status: 500 });
    }
}
