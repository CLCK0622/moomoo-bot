
import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
    try {
        // Path to the sentiment_report.json in ng-backend
        // Assuming ng-backend is a sibling of frontend
        const filePath = path.join(process.cwd(), '..', 'ng-backend', 'sentiment_report.json');

        if (!fs.existsSync(filePath)) {
            return NextResponse.json({ status: 'error', message: 'Sentiment report not found' }, { status: 404 });
        }

        const fileContent = fs.readFileSync(filePath, 'utf-8');
        const data = JSON.parse(fileContent);

        return NextResponse.json({ status: 'ok', data });
    } catch (error: any) {
        console.error('Error reading sentiment report:', error);
        return NextResponse.json({ status: 'error', message: 'Failed to read sentiment report' }, { status: 500 });
    }
}
