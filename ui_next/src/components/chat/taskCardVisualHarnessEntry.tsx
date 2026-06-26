import React from 'react';
import { createRoot } from 'react-dom/client';
import '../../index.css';
import { TaskCardVisualHarness } from './TaskCardVisualHarness';

createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <TaskCardVisualHarness />
  </React.StrictMode>
);
