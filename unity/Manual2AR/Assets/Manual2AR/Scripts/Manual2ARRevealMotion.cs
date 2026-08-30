using UnityEngine;

namespace Manual2AR
{
    /// <summary>
    /// Shared one-shot reveal used by every recording overlay. It fades and
    /// gently scales in once, then remains fully visible until the overlay is
    /// explicitly cleared. Repeated tracking updates do not restart it.
    /// </summary>
    [RequireComponent(typeof(CanvasGroup))]
    public sealed class Manual2ARRevealMotion : MonoBehaviour
    {
        [SerializeField, Range(0.12f, 0.60f)] float m_Duration = 0.28f;
        [SerializeField] bool m_UseScale = true;
        [SerializeField, Range(0.90f, 1.0f)] float m_StartScale = 0.965f;

        CanvasGroup m_CanvasGroup;
        Vector3 m_BaseScale;
        float m_StartedAt;
        bool m_Revealing;

        public void Configure(bool useScale)
        {
            m_UseScale = useScale;
        }

        void Awake()
        {
            EnsureCanvasGroup();
            m_BaseScale = transform.localScale;
        }

        void OnEnable()
        {
            if (!EnsureCanvasGroup())
                return;
            m_BaseScale = transform.localScale;
            m_StartedAt = Time.unscaledTime;
            m_Revealing = true;
            m_CanvasGroup.alpha = 0.0f;
            if (m_UseScale)
                transform.localScale = m_BaseScale * m_StartScale;
        }

        void Update()
        {
            if (!m_Revealing)
                return;
            // Overlay replacement uses Destroy(), which is deferred until the
            // end of the frame. A reveal component can therefore receive one
            // final Update after its sibling CanvasGroup was destroyed.
            if (!EnsureCanvasGroup())
            {
                m_Revealing = false;
                return;
            }
            var linear = Mathf.Clamp01((Time.unscaledTime - m_StartedAt) / Mathf.Max(0.01f, m_Duration));
            var eased = linear * linear * (3.0f - 2.0f * linear);
            m_CanvasGroup.alpha = eased;
            if (m_UseScale)
                transform.localScale = Vector3.LerpUnclamped(m_BaseScale * m_StartScale, m_BaseScale, eased);
            if (linear < 1.0f)
                return;
            m_Revealing = false;
            m_CanvasGroup.alpha = 1.0f;
            transform.localScale = m_BaseScale;
        }

        void OnDisable()
        {
            m_Revealing = false;
            if (m_CanvasGroup != null)
                m_CanvasGroup.alpha = 1.0f;
            transform.localScale = m_BaseScale == Vector3.zero ? Vector3.one : m_BaseScale;
        }

        bool EnsureCanvasGroup()
        {
            if (m_CanvasGroup)
                return true;
            if (!this || !gameObject)
                return false;
            m_CanvasGroup = GetComponent<CanvasGroup>();
            if (!m_CanvasGroup)
                m_CanvasGroup = gameObject.AddComponent<CanvasGroup>();
            return m_CanvasGroup;
        }
    }
}
