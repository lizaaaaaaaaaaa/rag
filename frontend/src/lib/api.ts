// frontend/src/lib/api.ts
const API_BASE_URL = "https://rag-api-190389115361.asia-northeast1.run.app";

export const callChatAPI = async (question: string, username?: string) => {
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "include",
      body: JSON.stringify({
        question: question,
        username: username || "guest"
      })
    });
    
    if (!response.ok) {
      console.error(`API Error: ${response.status} ${response.statusText}`);
      const errorText = await response.text();
      console.error("Error details:", errorText);
      throw new Error(`API Error: ${response.status}`);
    }
    
    return await response.json();
  } catch (error) {
    console.error("Fetch error:", error);
    throw error;
  }
};