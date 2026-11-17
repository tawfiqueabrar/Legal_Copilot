import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Legal Copilot", description: "Private legal document issue spotting" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
