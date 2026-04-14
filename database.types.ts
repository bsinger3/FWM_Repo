Need to install the following packages:
supabase@2.90.0
Ok to proceed? (y) export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "13.0.4"
  }
  graphql_public: {
    Tables: {
      [_ in never]: never
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      graphql: {
        Args: {
          extensions?: Json
          operationName?: string
          query?: string
          variables?: Json
        }
        Returns: Json
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
  public: {
    Tables: {
      "archive.images_backup_20260320_063904": {
        Row: {
          age_raw: string | null
          age_years_display: number | null
          brand: string | null
          bust_in_number_display: number | null
          bytes: string | null
          clothing_type_id: string | null
          color_canonical: string | null
          color_display: string | null
          content_type: string | null
          created_at_display: string | null
          cupsize_display: string | null
          date_review_submitted_raw: string | null
          fetched_at: string | null
          hash_md5: string | null
          height: string | null
          height_in_display: number | null
          height_raw: string | null
          hips_in_display: number | null
          hips_raw: string | null
          id: string | null
          inseam_inches_display: number | null
          monetized_product_url_display: string | null
          original_url_display: string | null
          product_page_url_display: string | null
          review_date: string | null
          reviewer_name_raw: string | null
          reviewer_profile_url: string | null
          search_fts: string | null
          size_display: string | null
          source_site_display: string | null
          status_code: string | null
          updated_at: string | null
          user_comment: string | null
          waist_in: string | null
          waist_raw_display: string | null
          weight_display_display: string | null
          weight_lb: string | null
          weight_lbs_display: number | null
          weight_lbs_raw_issue: string | null
          weight_raw: string | null
          weight_raw_needs_correction: string | null
          width: string | null
        }
        Insert: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string | null
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id?: string | null
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display?: string | null
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Update: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string | null
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id?: string | null
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display?: string | null
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Relationships: []
      }
      clothing_types: {
        Row: {
          id: string
          label: string
          sort_order: number
        }
        Insert: {
          id: string
          label: string
          sort_order?: number
        }
        Update: {
          id?: string
          label?: string
          sort_order?: number
        }
        Relationships: []
      }
      images: {
        Row: {
          age_raw: string | null
          age_years_display: number | null
          brand: string | null
          bust_in_number_display: number | null
          bytes: string | null
          clothing_type_id: string | null
          color_canonical: string | null
          color_display: string | null
          content_type: string | null
          created_at_display: string
          cupsize_display: string | null
          date_review_submitted_raw: string | null
          fetched_at: string | null
          hash_md5: string | null
          height: string | null
          height_in_display: number | null
          height_raw: string | null
          hips_in_display: number | null
          hips_raw: string | null
          id: string
          inseam_inches_display: number | null
          monetized_product_url_display: string | null
          original_url_display: string | null
          product_page_url_display: string | null
          review_date: string | null
          reviewer_name_raw: string | null
          reviewer_profile_url: string | null
          search_fts: string | null
          size_display: string
          source_site_display: string | null
          status_code: string | null
          updated_at: string | null
          user_comment: string | null
          waist_in: string | null
          waist_raw_display: string | null
          weight_display_display: string | null
          weight_lb: string | null
          weight_lbs_display: number | null
          weight_lbs_raw_issue: string | null
          weight_raw: string | null
          weight_raw_needs_correction: string | null
          width: string | null
        }
        Insert: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id: string
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display: string
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Update: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id?: string
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display?: string
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "images_clothing_type_fk"
            columns: ["clothing_type_id"]
            isOneToOne: false
            referencedRelation: "clothing_types"
            referencedColumns: ["id"]
          },
        ]
      }
      images_backup_20260320: {
        Row: {
          age_raw: string | null
          age_years_display: number | null
          brand: string | null
          bust_in_number_display: number | null
          bytes: string | null
          clothing_type_id: string | null
          color_canonical: string | null
          color_display: string | null
          content_type: string | null
          created_at_display: string | null
          cupsize_display: string | null
          date_review_submitted_raw: string | null
          fetched_at: string | null
          hash_md5: string | null
          height: string | null
          height_in_display: number | null
          height_raw: string | null
          hips_in_display: number | null
          hips_raw: string | null
          id: string | null
          inseam_inches_display: number | null
          monetized_product_url_display: string | null
          original_url_display: string | null
          product_page_url_display: string | null
          review_date: string | null
          reviewer_name_raw: string | null
          reviewer_profile_url: string | null
          search_fts: string | null
          size_display: string | null
          source_site_display: string | null
          status_code: string | null
          updated_at: string | null
          user_comment: string | null
          waist_in: string | null
          waist_raw_display: string | null
          weight_display_display: string | null
          weight_lb: string | null
          weight_lbs_display: number | null
          weight_lbs_raw_issue: string | null
          weight_raw: string | null
          weight_raw_needs_correction: string | null
          width: string | null
        }
        Insert: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string | null
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id?: string | null
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display?: string | null
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Update: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string | null
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id?: string | null
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display?: string | null
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Relationships: []
      }
      images_staging: {
        Row: {
          age_raw: string | null
          age_years_display: number | null
          brand: string | null
          bust_in_number_display: number | null
          bytes: string | null
          clothing_type_id: string | null
          color_canonical: string | null
          color_display: string | null
          content_type: string | null
          created_at_display: string | null
          cupsize_display: string | null
          date_review_submitted_raw: string | null
          fetched_at: string | null
          hash_md5: string | null
          height: string | null
          height_in_display: number | null
          height_raw: string | null
          hips_in_display: number | null
          hips_raw: string | null
          id: string | null
          inseam_inches_display: number | null
          monetized_product_url_display: string | null
          original_url_display: string | null
          product_page_url_display: string | null
          review_date: string | null
          reviewer_name_raw: string | null
          reviewer_profile_url: string | null
          search_fts: string | null
          size_display: string | null
          source_site_display: string | null
          status_code: string | null
          updated_at: string | null
          user_comment: string | null
          waist_in: string | null
          waist_raw_display: string | null
          weight_display_display: string | null
          weight_lb: string | null
          weight_lbs_display: number | null
          weight_lbs_raw_issue: string | null
          weight_raw: string | null
          weight_raw_needs_correction: string | null
          width: string | null
        }
        Insert: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string | null
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id?: string | null
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display?: string | null
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Update: {
          age_raw?: string | null
          age_years_display?: number | null
          brand?: string | null
          bust_in_number_display?: number | null
          bytes?: string | null
          clothing_type_id?: string | null
          color_canonical?: string | null
          color_display?: string | null
          content_type?: string | null
          created_at_display?: string | null
          cupsize_display?: string | null
          date_review_submitted_raw?: string | null
          fetched_at?: string | null
          hash_md5?: string | null
          height?: string | null
          height_in_display?: number | null
          height_raw?: string | null
          hips_in_display?: number | null
          hips_raw?: string | null
          id?: string | null
          inseam_inches_display?: number | null
          monetized_product_url_display?: string | null
          original_url_display?: string | null
          product_page_url_display?: string | null
          review_date?: string | null
          reviewer_name_raw?: string | null
          reviewer_profile_url?: string | null
          search_fts?: string | null
          size_display?: string | null
          source_site_display?: string | null
          status_code?: string | null
          updated_at?: string | null
          user_comment?: string | null
          waist_in?: string | null
          waist_raw_display?: string | null
          weight_display_display?: string | null
          weight_lb?: string | null
          weight_lbs_display?: number | null
          weight_lbs_raw_issue?: string | null
          weight_raw?: string | null
          weight_raw_needs_correction?: string | null
          width?: string | null
        }
        Relationships: []
      }
      search_events: {
        Row: {
          anon_id: string
          bust_in: number | null
          clothing_type: string | null
          created_at: string
          feet: number | null
          hips_in: number | null
          id: string
          inches: number | null
          latency_ms: number | null
          page_url: string | null
          referrer: string | null
          results_count: number | null
          session_id: string
          utm_campaign: string | null
          utm_content: string | null
          utm_medium: string | null
          utm_source: string | null
          weight_lb: number | null
        }
        Insert: {
          anon_id: string
          bust_in?: number | null
          clothing_type?: string | null
          created_at?: string
          feet?: number | null
          hips_in?: number | null
          id?: string
          inches?: number | null
          latency_ms?: number | null
          page_url?: string | null
          referrer?: string | null
          results_count?: number | null
          session_id: string
          utm_campaign?: string | null
          utm_content?: string | null
          utm_medium?: string | null
          utm_source?: string | null
          weight_lb?: number | null
        }
        Update: {
          anon_id?: string
          bust_in?: number | null
          clothing_type?: string | null
          created_at?: string
          feet?: number | null
          hips_in?: number | null
          id?: string
          inches?: number | null
          latency_ms?: number | null
          page_url?: string | null
          referrer?: string | null
          results_count?: number | null
          session_id?: string
          utm_campaign?: string | null
          utm_content?: string | null
          utm_medium?: string | null
          utm_source?: string | null
          weight_lb?: number | null
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      format_weight_display: {
        Args: { p_weight_lb: number; p_weight_raw: string }
        Returns: string
      }
      host_name: { Args: { u: string }; Returns: string }
      inspect_table_columns_examples: {
        Args: { example_limit?: number; in_schema: string; in_table: string }
        Returns: {
          character_maximum_length: number
          column_name: string
          data_type: string
          distinct_count: number
          examples: string[]
          is_nullable: string
          max_value: string
          min_value: string
        }[]
      }
      match_by_measurements: {
        Args: {
          in_bust?: number
          in_clothing_type_id?: string
          in_height?: number
          in_hips?: number
          in_waist?: number
          in_weight?: number
          limit_n?: number
          offset_n?: number
          require_bust?: boolean
          require_height?: boolean
          require_hips?: boolean
          require_waist?: boolean
          require_weight?: boolean
        }
        Returns: {
          age_years_display: number | null
          brand: string | null
          bust_in_number_display: number | null
          color_display: string | null
          cupsize_display: string | null
          height_in_display: number | null
          id: string
          inseam_inches_display: number | null
          monetized_product_url_display: string | null
          original_url_display: string | null
          product_page_url_display: string | null
          size_display: string
          source_site_display: string | null
          waist_in: string | null
          weight_display_display: string | null
          hips_in_display: number | null
        }[]
      }
      match_by_measurements_deprecated:
        | {
            Args: {
              in_bust?: number
              in_height?: number
              in_hips?: number
              in_waist?: number
              in_weight?: number
              limit_n?: number
              offset_n?: number
            }
            Returns: {
              brand: string | null
              color_ordered_raw: string | null
              height_in: number | null
              id: string
              monetized_product_url: string | null
              original_url: string | null
              product_page_url: string | null
              size_ordered_raw: string | null
              source_site: string | null
              weight_lb: number | null
            }[]
          }
        | {
            Args: {
              color_raw?: string
              in_bust?: number
              in_height?: number
              in_hips?: number
              in_waist?: number
              in_weight?: number
              limit_n?: number
              offset_n?: number
              retailer?: string
              size_raw?: string
            }
            Returns: {
              brand: string | null
              color_ordered_raw: string | null
              created_at: string | null
              height_in: number | null
              id: string
              monetized_product_url: string | null
              original_url: string | null
              product_page_url: string | null
              score: number | null
              size_ordered_raw: string | null
              source_site: string | null
              weight_display: string | null
              weight_lb: number | null
            }[]
          }
      parse_age_years: { Args: { t: string }; Returns: number }
      parse_height_in: { Args: { t: string }; Returns: number }
      parse_inches: { Args: { t: string }; Returns: number }
      parse_weight_lb: { Args: { t: string }; Returns: number }
      search_catalog_deprecated: {
        Args: {
          color_raw?: string
          end_date?: string
          limit_n?: number
          max_height?: number
          min_height?: number
          offset_n?: number
          q?: string
          retailer?: string
          size_raw?: string
          start_date?: string
        }
        Returns: unknown[]
        SetofOptions: {
          from: "*"
          to: "images_public"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      show_limit: { Args: never; Returns: number }
      show_trgm: { Args: { "": string }; Returns: string[] }
      update_search_event_metrics: {
        Args: { p_id: string; p_latency_ms: number; p_results_count: number }
        Returns: undefined
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  graphql_public: {
    Enums: {},
  },
  public: {
    Enums: {},
  },
} as const
