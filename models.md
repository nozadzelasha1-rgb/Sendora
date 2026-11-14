Table dbo.dictionary_spec {
  id bigint [pk, increment]
  name text [not null, note: 'назва категорії, напр. order_status']

  Note: '''Категорії довідника'''
}

Table dbo.dictionary {
  id bigint [pk, increment]
  spec_id bigint [not null, ref: > dbo.dictionary_spec.id]
  name text [not null, note: 'код значення, напр. CREATED']
  description text

  Note: '''Значення довідника для всіх полів типу enum та ролей, типів і статусів'''
}

Table dbo.organizations {
  id uuid [pk, default: `gen_random_uuid()`]
  name text [not null]
  type bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: organization_type']
  contact text
  phone varchar(20)
  delivery_fee_gel numeric(12,2)
  active boolean [not null, default: true]

  Note: '''Аркуш Organizations: партнери та оператор Sendora'''
}

Table dbo.users {
  id uuid [pk, default: `gen_random_uuid()`]
  name text [not null, unique] 
  role bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: user_role']
  organization_id uuid [not null, ref: > dbo.organizations.id]
  zone_id uuid [ref: > dbo.zones.id]
  active boolean [not null, default: true]
  email varchar(255) [unique]
  phone varchar(20) [unique]
  password_hash text

  Note: '''Аркуші Managers, Roles and Access, Infrastructure (вхід за email або телефоном і паролем): менеджери, диспетчери, кур'єри, користувачі партнерів'''
}

Table dbo.user_sessions {
  id uuid [pk, default: `gen_random_uuid()`]
  user_id uuid [not null]
  refresh_token_hash bytea [not null, unique]
  previous_token_hash bytea
  created_at timestamptz [not null, default: `now()`]
  rotated_at timestamptz
  expires_at timestamptz [not null]
  revoked_at timestamptz
  revoked_reason varchar(20)


  Note: '''Сесії входу: хеш refresh-токена з ротацією; відкликана сесія має revoked_at і причину'''
}

Ref: dbo.user_sessions.user_id > dbo.users.id [delete: cascade]

Table dbo.zones {
  id uuid [pk, default: `gen_random_uuid()`]
  name text [not null]
  city text [not null]
  boundary jsonb [note: 'межі / полігон зони']
  manager_id uuid [ref: > dbo.users.id]
  assignment_rule bigint [ref: > dbo.dictionary.id, note: 'dictionary: zone_assignment_rule']
  status bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: zone_status']

  Note: '''Аркуш Delivery Zones'''
}

Table dbo.orders {
  id bigint [pk, increment]
  tracking_number text [not null, unique, note: 'SD-YYYY-NNNNNN, генерується системою']
  external_order_id text
  partner_id uuid [not null, ref: > dbo.organizations.id]
  service_type bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: service_type']
  zone_id uuid [ref: > dbo.zones.id]
  courier_id uuid [ref: > dbo.users.id]
  status bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: order_status']
  tracking_url text
  created_at timestamptz [not null, default: `now()`]
  updated_at timestamptz [not null, default: `now()`]
  delivered_at timestamptz

  Note: '''Ядро замовлення: ідентифікація, статус і ключі фільтрації списків'''

 indexes {
    (partner_id, external_order_id) [unique]
  }
}

Table dbo.order_status_history {
  id bigint [pk, increment]
  order_id bigint [not null, ref: > dbo.orders.id]
  status bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: order_status']
  exception_reason bigint [ref: > dbo.dictionary.id, note: 'dictionary: exception_reason']
  next_action bigint [ref: > dbo.dictionary.id, note: 'dictionary: order_status - запланований наступний статус']
  comment text
  changed_by uuid [ref: > dbo.users.id]
  created_at timestamptz [not null, default: `now()`]

  Note: '''Кожна зміна статусу замовлення; лише дописування, записи не змінюються і не видаляються'''
}
Table dbo.order_senders {
  order_id bigint [pk, ref: - dbo.orders.id]
  sender_company text [not null]
  sender_contact text [not null]
  sender_phone varchar(20) [not null]
  pickup_address text
  sender_comment text

  Note: '''Група Sender'''
}

Table dbo.order_recipients {
  order_id bigint [pk, ref: - dbo.orders.id]
  recipient_name text [not null]
  recipient_phone varchar(20) [not null]
  recipient_alt_phone varchar(20)
  delivery_address text [not null]
  city text [not null]
  entrance text
  floor text
  apartment text
  door_code text
  landmark text

  Note: '''Група Recipient'''
}

Table dbo.order_parcels {
  order_id bigint [pk, ref: - dbo.orders.id]
  parcel_type bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: parcel_type']
  pieces_count smallint [not null, default: 1]
  weight_kg numeric(7,3)
  length_cm numeric(6,1)
  width_cm numeric(6,1)
  height_cm numeric(6,1)
  description text
  fragile boolean [not null, default: false]
  declared_value_gel numeric(12,2)

  Note: '''Група Parcel'''
}

Table dbo.order_schedules {
  order_id bigint [pk, ref: - dbo.orders.id]
  pickup_date date
  pickup_window varchar(11) [note: 'HH:MM-HH:MM']
  requested_delivery_date date
  delivery_window varchar(11) [note: 'HH:MM-HH:MM']

  Note: '''Дати та часові вікна забору й доставки'''
}

Table dbo.order_payments {
  order_id bigint [pk, ref: - dbo.orders.id]
  delivery_payer bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: delivery_payer']
  delivery_fee_gel numeric(12,2) [not null]
  cod_enabled boolean [not null, default: false]
  cod_amount_gel numeric(12,2) [not null, default: 0]
  currency bigint [not null, ref: > dbo.dictionary.id, note: 'dictionary: currency']
  cod_method bigint [ref: > dbo.dictionary.id, note: 'dictionary: cod_method']

  Note: '''Група Payment'''
}

Table dbo.order_operations {
  order_id bigint [pk, ref: - dbo.orders.id]
  carrier_id varchar(32) [note: 'Фаза 2; таблиця перевізників у специфікації не описана']
  manager_id uuid [ref: > dbo.users.id]сд
  route_id varchar(32) [note: 'Фаза 2; таблиця маршрутів у специфікації не описана']
  latitude numeric(9,6)
  longitude numeric(9,6)
  internal_comment text

  Note: '''Група Operations: внутрішні поля, які партнер не бачить'''
}