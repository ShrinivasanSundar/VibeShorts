"use client";

import React, { useState } from "react";
import { Navbar } from "@/components/layout/Navbar";
import { ChatContainer } from "@/components/chat/ChatContainer";
import { ChatInput } from "@/components/chat/ChatInput";
import { CompactEditModal } from "@/components/editor/CompactEditModal";
import { MediaUploadModal } from "@/components/modals/MediaUploadModal";
import { useTheme } from "@/hooks/useTheme";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import { useChat } from "@/hooks/useChat";

export default function Home() {
  const { theme, toggleTheme } = useTheme();
  const backendOnline = useBackendHealth();

  const {
    projectId,
    currentPlan,
    videoUrl,
    jobStatus,
    isGenerating,
    isRenderingTimeline,
    uploadedCount,
    messages,
    resetProject,
    handleUploadComplete,
    handleSendMessage,
    handleUpdatePlan,
    handleReRender,
  } = useChat(backendOnline);

  // Modal state
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedCutForModal, setSelectedCutForModal] = useState<number | null>(null);

  const handleSelectCut = (cutIndex: number) => {
    setSelectedCutForModal(cutIndex);
    setIsEditModalOpen(true);
  };

  return (
    <main className="h-screen max-h-screen bg-background text-foreground flex flex-col items-center overflow-hidden bg-dot-grid">
      {/* Top Navbar */}
      <Navbar
        theme={theme}
        onToggleTheme={toggleTheme}
        backendOnline={backendOnline}
        uploadedCount={uploadedCount}
        onOpenUpload={() => setIsUploadOpen(true)}
        onNewProject={resetProject}
        projectId={projectId}
      />

      {/* Centred Conversational Chat Layout */}
      <div className="flex-1 w-full max-w-2xl flex flex-col justify-between overflow-hidden px-4 pb-3.5 mx-auto">
        <ChatContainer
          messages={messages}
          isGenerating={isGenerating}
          activeJob={jobStatus}
          onSelectCut={handleSelectCut}
          onOpenEditor={() => setIsEditModalOpen(true)}
        />

        <div className="flex-shrink-0 pt-2 w-full">
          <ChatInput
            onSendMessage={handleSendMessage}
            onOpenUpload={() => setIsUploadOpen(true)}
            uploadedCount={uploadedCount}
            isLoading={isGenerating || isRenderingTimeline}
          />
        </div>
      </div>

      {/* Timeline Editor Modal */}
      <CompactEditModal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        plan={currentPlan}
        onUpdatePlan={handleUpdatePlan}
        onTriggerReRender={handleReRender}
        isRendering={isRenderingTimeline}
        initialCutIndex={selectedCutForModal}
        videoSrc={videoUrl}
      />

      {/* Footage Upload Modal */}
      <MediaUploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        projectId={projectId}
        onUploadComplete={handleUploadComplete}
        existingFiles={[]}
      />
    </main>
  );
}
