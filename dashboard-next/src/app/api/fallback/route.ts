import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import { join } from "path";

export async function GET() {
  try {
    // Read from the bot's logs directory (relative to project root)
    const filePath = join(process.cwd(), "..", "logs", "dashboard_data.json");
    const data = await readFile(filePath, "utf-8");
    return NextResponse.json(JSON.parse(data));
  } catch {
    return NextResponse.json(
      { error: "dashboard_data.json not available" },
      { status: 404 }
    );
  }
}
