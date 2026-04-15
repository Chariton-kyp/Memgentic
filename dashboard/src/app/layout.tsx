import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { Providers } from "@/components/providers";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { AuthLayout } from "@/components/auth-layout";

export const metadata: Metadata = {
  title: "Memgentic Dashboard",
  description: "Universal AI Memory Layer — Dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <Providers>
          <TooltipProvider>
            <AuthLayout>{children}</AuthLayout>
          </TooltipProvider>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
