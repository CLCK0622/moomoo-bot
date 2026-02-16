import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import path from 'path';
import util from 'util';

const execPromise = util.promisify(exec);

export async function GET() {
    try {
        // Resolve paths
        const backendDir = path.resolve(process.cwd(), '../ng-backend');
        const venvPython = path.join(backendDir, 'venv/bin/python');
        const scriptPath = path.join(backendDir, 'fetch_quotes.py');

        // Execute the python script
        const { stdout, stderr } = await execPromise(`${venvPython} ${scriptPath}`);

        if (stderr && stderr.length > 0) {
            // Log stderr but don't fail immediately if stdout has data, as we use stderr for debug
            console.error('Python Stderr:', stderr);
        }

        // Extract JSON from stdout (ignoring log lines)
        const lines = stdout.split('\n');
        let data = null;

        for (const line of lines) {
            const trimmed = line.trim();
            if ((trimmed.startsWith('{') && trimmed.endsWith('}')) ||
                (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
                try {
                    data = JSON.parse(trimmed);
                    break;
                } catch (e) {
                    // Not valid JSON, continue
                }
            }
        }

        if (!data) {
            console.error('No valid JSON found in output:', stdout);
            return NextResponse.json({ status: 'error', message: 'No JSON output from script' }, { status: 500 });
        }

        return NextResponse.json(data);

    } catch (error: any) {
        console.error('Error executing quote script:', error);
        return NextResponse.json({ status: 'error', message: error.message || 'Script execution failed' }, { status: 500 });
    }
}
