-- Create users table with explicit schema and constraints
create table public.users (
  id uuid not null default auth.uid(),
  name character varying(255) not null,
  email character varying(255) not null,
  password character varying(255) not null,
  date_of_birth date not null,
  otp character varying(6) null,
  created_at timestamp with time zone not null default timezone('utc'::text, now()),
  constraint users_pkey primary key (id),
  constraint users_email_key unique (email)
) TABLESPACE pg_default;

-- Create saved_articles table with explicit schema reference
create table public.saved_articles (
  id uuid not null default uuid_generate_v4(),
  user_id uuid not null,
  title text not null,
  url text not null,
  image_url text, -- Changed from urlToImage to image_url
  created_at timestamp with time zone not null default timezone('utc'::text, now()),
  constraint saved_articles_pkey primary key (id),
  constraint saved_articles_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade
) TABLESPACE pg_default;

-- Enable Row Level Security
alter table public.users enable row level security;
alter table public.saved_articles enable row level security;

-- Create RLS policies for users table
create policy "Users can view their own data" on public.users
  for select using (auth.uid() = id);

create policy "Users can update their own data" on public.users
  for update using (auth.uid() = id);

-- Create RLS policies for saved_articles table
create policy "Users can view their own saved articles" on public.saved_articles
  for select using (auth.uid() = user_id);

create policy "Users can insert their own articles" on public.saved_articles
  for insert with check (auth.uid() = user_id);

create policy "Users can delete their own saved articles" on public.saved_articles
  for delete using (auth.uid() = user_id);
