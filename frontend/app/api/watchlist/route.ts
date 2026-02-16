import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

// Path to the watchlist.json file
// The requirement is ../ng-backend/watchlist.json relative to the frontend directory
// In a Next.js app in development, process.cwd() is usually the project root (frontend)
const WATCHLIST_PATH = path.join(process.cwd(), '../ng-backend/watchlist.json');

export async function GET() {
  try {
    const data = await fs.readFile(WATCHLIST_PATH, 'utf-8');
    const json = JSON.parse(data);
    return NextResponse.json(json);
  } catch (error) {
    console.error('Error reading watchlist:', error);
    return NextResponse.json({ error: 'Failed to read watchlist' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { symbols } = body;

    if (!Array.isArray(symbols)) {
      return NextResponse.json({ error: 'Invalid data format' }, { status: 400 });
    }

    // Read existing file to preserve structure if needed, or just overwrite since we manage the whole list
    const newData = JSON.stringify({ symbols }, null, 2);
    await fs.writeFile(WATCHLIST_PATH, newData, 'utf-8');

    return NextResponse.json({ success: true, symbols });
  } catch (error) {
    console.error('Error writing watchlist:', error);
    return NextResponse.json({ error: 'Failed to update watchlist' }, { status: 500 });
  }
}
