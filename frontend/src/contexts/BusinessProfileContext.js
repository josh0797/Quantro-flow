import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

const BusinessProfileContext = createContext();

export function useBusinessProfile() {
  const context = useContext(BusinessProfileContext);
  if (!context) {
    throw new Error('useBusinessProfile must be used within BusinessProfileProvider');
  }
  return context;
}

export function BusinessProfileProvider({ children }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchProfile = useCallback(async () => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const response = await fetch(`${backendUrl}/api/business-profile`);
      if (response.ok) {
        const data = await response.json();
        setProfile(data);
      }
    } catch (error) {
      console.error('Failed to fetch business profile:', error);
      // Set default fallback profile
      setProfile({
        profile_id: 'default',
        industry: 'other',
        use_case: '',
        entity_labels: {
          contacts: 'Contacts',
          team_members: 'Team Members',
          meetings: 'Meetings',
          events: 'Events',
          services: 'Services'
        }
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  const updateProfile = async (newProfile) => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const response = await fetch(`${backendUrl}/api/business-profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newProfile)
      });
      
      if (response.ok) {
        const updated = await response.json();
        setProfile(updated);
        return updated;
      }
    } catch (error) {
      console.error('Failed to update business profile:', error);
      throw error;
    }
  };

  // Helper function to get label for entity type
  const getLabel = (entityType, fallback) => {
    if (!profile || !profile.entity_labels) return fallback;
    return profile.entity_labels[entityType] || fallback;
  };

  const value = {
    profile,
    loading,
    updateProfile,
    refetch: fetchProfile,
    getLabel,
    // Quick accessors
    labels: profile?.entity_labels || {},
    industry: profile?.industry || 'other',
    useCase: profile?.use_case || '',
  };

  return (
    <BusinessProfileContext.Provider value={value}>
      {children}
    </BusinessProfileContext.Provider>
  );
}
