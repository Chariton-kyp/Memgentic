"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setApiKey, clearApiKey, getMe } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function LoginPage() {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      setApiKey(key.trim());
      const me = await getMe();
      if (me.authenticated) {
        router.push("/");
      } else {
        setError("Invalid API key");
        clearApiKey();
      }
    } catch {
      setError("Invalid API key or server unreachable");
      clearApiKey();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Memgentic</CardTitle>
          <p className="text-sm text-muted-foreground">
            Enter your API key to access your memories
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              type="password"
              placeholder="memgentic_sk_..."
              value={key}
              onChange={(e) => setKey(e.target.value)}
              aria-label="API Key"
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button
              type="submit"
              className="w-full"
              disabled={loading || !key.trim()}
            >
              {loading ? "Connecting..." : "Connect"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
