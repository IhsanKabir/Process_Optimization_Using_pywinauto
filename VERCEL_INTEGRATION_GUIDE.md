# Vercel & Next.js API Integration Guide

Now that the `.exe` is programmed to ask your website for instructions, you need to set up the backend API on your Next.js Vercel app to respond to those requests.

## 1. Update `config.json`
On your local machine (and in the package you ZIP up for your clients), update your `config.json` to include the `commands_url`.

```json
{
  "commands_url": "https://your-website.com/api/travelport-agent",
  "api_key": "optional-secret-token",
  "commands_file": "commands.txt",
  "...": "rest of your config"
}
```

## 2. Setting up the Next.js API Route
Since your website is deployed on Vercel, you are likely using Next.js. We will create an API route using the **App Router** (`app/api/...`) that queries your Neon database (or BigQuery) for the routes the user selected.

Create a new file in your Next.js project:
`app/api/travelport-agent/route.ts`

Paste the following boilerplate code into it:

```typescript
import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  // Optional: Check API Key if you provided one in config.json
  const authHeader = request.headers.get('authorization');
  if (authHeader !== 'Bearer optional-secret-token') {
    // return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  // TODO: Replace this mock data loop with your actual Neon/BigQuery logic.
  // Example: SELECT route_string FROM user_tasks WHERE user_id = X AND status = 'pending'
  
  // The Python App accepts either a JSON array of parsed objects OR a plain raw text string list.
  // Providing the raw text string list is the easiest way to bridge the gap.
  
  const clientCommands = [
    "FDDACMCT/BG",
    "FDDACDOH/QR",
    "FDDACCCU/WY"
  ];

  // Join the arrays into a raw string exactly like commands.txt
  const rawTextOutput = clientCommands.join('\n');

  // Return the data as plaintext, just like the script expects!
  return new NextResponse(rawTextOutput, {
    status: 200,
    headers: {
      'Content-Type': 'text/plain',
    },
  });
}
```

## 3. How the Cloud Loop Works
1. Your client clicks checkboxes on your website dashboard (e.g., "MCT", "DOH", "CCU"). Your Next.js app saves these into your Neon database.
2. The client double-clicks `.exe` on their desktop.
3. The `.exe` pings `https://your-website.com/api/travelport-agent`.
4. Your API runs the `GET` function, connects to Neon, pulls the pending tasks, formats them, and returns them to the Python script.
5. The Python script instantly grabs Travelport on their machine and extracts the fares.
6. *(Next Step)*: In the future, you can write a `POST /api/travelport-agent` endpoint where the Python script uploads the final Excel file back to your website!
