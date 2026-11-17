CREATE TABLE IF NOT EXISTS providers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category text NOT NULL,
    name text NOT NULL,
    phone text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    premium integer NOT NULL DEFAULT 0,
    description text NOT NULL DEFAULT '',
    photo text NOT NULL DEFAULT '',
    reviews text NOT NULL DEFAULT '[]',
    UNIQUE (category, phone)
);
