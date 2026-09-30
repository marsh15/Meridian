import type { Metadata, Viewport } from "next";
import "../styles/tokens.css";
import "../styles/app.css";
import { Providers } from "../providers";
import Header from "../components/Header";
import TickerTape from "../components/TickerTape";
import AuthModal from "../components/AuthModal";

export const metadata: Metadata = {
  title: "Meridian — Trade on What Happens Next",
  description:
    "Meridian is a prediction market exchange. Create markets, trade Yes and No shares on politics, economics, crypto, sports and science.",
  openGraph: {
    title: "Meridian — Trade on What Happens Next",
    description:
      "Create markets, trade Yes and No shares on politics, economics, crypto, sports and science. Instant fills, prices set by the crowd.",
    type: "website",
  },
  icons: {
    icon: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232747C4'/%3E%3Cpath d='M8 16l8-8 8 8-8 8z' fill='%23FFFDF8'/%3E%3C/svg%3E",
  },
};

export const viewport: Viewport = {
  themeColor: "#f5f1e8",
};

function Logo() {
  return (
    <span className="footer-logo">
      <span className="logo-mark" aria-hidden="true">
        <svg viewBox="0 0 14 14" fill="none">
          <path d="M1 7L7 1l6 6-6 6z" fill="currentColor" />
        </svg>
      </span>
      Meridian
    </span>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700&family=Instrument+Sans:ital,wght@0,400..700;1,400..700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <Providers>
          <Header />
          <TickerTape />
          {children}
          <footer className="site-footer">
            <div className="wrap footer-inner">
              <Logo />
              <div className="footer-note">
                <span>Prediction market demo — play money only</span>
                <span className="sep">·</span>
                <span>Not financial advice</span>
              </div>
            </div>
          </footer>
          <AuthModal />
        </Providers>
      </body>
    </html>
  );
}
