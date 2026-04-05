'use client';

import { useEffect, useRef, useState } from 'react';
import {
  PipecatClientAudio,
  PipecatClientVideo,
  usePipecatClientTransportState,
} from '@pipecat-ai/client-react';
import { ConnectButton } from '../../components/ConnectButton';
import { StatusDisplay } from '../../components/StatusDisplay';
import { DebugDisplay } from '../../components/DebugDisplay';

import { useSearchParams } from 'next/navigation';

function BotVideo() {
  const transportState = usePipecatClientTransportState();
  const isReady = transportState === 'ready';

  return (
    <div className="bot-container">
      <div className="video-container">
        {isReady && <PipecatClientVideo participant="bot" fit="cover" />}
        
        {!isReady && (
          <div className="loading-overlay">
            ⏳ Waiting for the interviewer to be ready...
          </div>
        )}
      </div>
    </div>
  );
}

export default function Home() {
  const searchParams = useSearchParams();
  const userId = searchParams.get('user_id');
  const language = searchParams.get('lang');

  const transportState = usePipecatClientTransportState();
  const ONE_SECOND_MS = 1000;
  const SESSION_SECOND_LIMIT = 600; // 10 min
  const [timeLeft, setTimeLeft] = useState(SESSION_SECOND_LIMIT);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const formatTime = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;

  useEffect(() => {
    console.log("transportState:", transportState);

    // 🔵 Case 1: connected → reset timer
    if (transportState === 'connected') {
      console.log("🔄 Reset timer to 10 minutes");
      setTimeLeft(SESSION_SECOND_LIMIT);

      // clear any old timers
      if (timerRef.current) clearInterval(timerRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);

      return;
    }

    // 🟢 Case 2: ready → start countdown
    if (transportState === 'ready') {
      console.log("✅ Start countdown");

      // prevent multiple timers
      if (timerRef.current) return;

      timerRef.current = setInterval(() => {
        setTimeLeft((t) => Math.max(t - 1, 0));
      }, ONE_SECOND_MS);

      timeoutRef.current = setTimeout(() => {
        console.log("⏰ Timeout reached");
        // TODO: Handle this more carefully
        alert("Interview session ended (10 minutes)");
        window.location.reload();
      }, SESSION_SECOND_LIMIT * ONE_SECOND_MS);
    }

    // 🔴 Case 3: disconnected → cleanup
    if (transportState === 'disconnected') {
      console.log("🧹 Cleanup on disconnect");

      if (timerRef.current) clearInterval(timerRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);

      timerRef.current = null;
      timeoutRef.current = null;
    }

  }, [transportState]);

  if (!userId) {
    return <div>Missing user_id. Please register first.</div>;
  }
  
  return (
    <div className="app">
      <div className="status-bar">
        <StatusDisplay />
        {(transportState === 'connected') && <div>⏳ Preparing interview...</div>}
        {(transportState === 'ready') && <div>Time left: {formatTime(timeLeft)}</div>}
        <ConnectButton userId={userId} lang={language}/>
      </div>

      <div className="main-content">
        <BotVideo />
      </div>

      <DebugDisplay />
      <PipecatClientAudio />
    </div>
  );
}
